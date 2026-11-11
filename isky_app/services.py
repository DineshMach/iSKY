from datetime import timedelta
from decimal import Decimal
import secrets
import uuid
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from .helper import sync_student_fee_concessions
from .models import FeeConcession, FeePayment, PaymentGatewayLink, PaymentHistory, SettlementBatch, SettlementBatchItem, StudentFeeInvoice, StudentFeeInvoiceItem


class InvoiceAlreadyExists(Exception):
    pass


def _best_concession_for_category(concessions, category, gross_amount, today):
    best, best_off = None, Decimal("0")
    for c in concessions:
        if c.category_id not in (None, category.id):
            continue
        if not c.is_applicable_on(today):
            continue
        off = c.amount_off(gross_amount)
        if off > best_off:
            best, best_off = c, off
    return best, best_off


@transaction.atomic
def generate_invoice_for_student(student, fee_structure, semester, due_date, today=None):
    today = today or timezone.now().date()
    if StudentFeeInvoice.objects.filter(student=student, fee_structure=fee_structure, semester=semester).exists():
        raise InvoiceAlreadyExists()
    items_qs = fee_structure.items.filter(is_active=True).select_related("category")
    sync_student_fee_concessions(student=student,today=today)
    if fee_structure.billing_cycle == "semester":
        items_qs = items_qs.filter(Q(semester=semester) | Q(semester__isnull=True))
    concessions = list(FeeConcession.objects.filter(student=student, is_active=True).select_related("category"))
    invoice = StudentFeeInvoice.objects.create(student=student,fee_structure=fee_structure,academic_year=fee_structure.academic_year,semester=semester,total_amount=Decimal("0"),discount_amount=Decimal("0"),due_date=due_date,)
    total_amount = Decimal("0")
    total_discount = Decimal("0")
    for item in items_qs:
        gross = item.amount
        concession, off = _best_concession_for_category(concessions, item.category, gross, today)
        net = gross - off
        StudentFeeInvoiceItem.objects.create(invoice=invoice,category=item.category,gross_amount=gross,concession=concession,concession_amount=off,amount=net,)
        total_amount += gross
        total_discount += off
    invoice.total_amount = total_amount
    invoice.discount_amount = total_discount
    invoice.save(update_fields=["total_amount", "discount_amount", "updated_at"])
    invoice.refresh_status()
    return invoice



class NothingToPayError(Exception):
    pass
 
 
@transaction.atomic
def generate_payment_link(invoice, created_by=None, validity_minutes=30):
    balance = invoice.balance_due
    if balance <= 0:
        raise NothingToPayError()
 
    PaymentGatewayLink.objects.filter(invoice=invoice, status="active").update(status="inactive", updated_at=timezone.now())
    return PaymentGatewayLink.objects.create(invoice=invoice,student=invoice.student,token=secrets.token_urlsafe(32),amount=balance,expires_at=timezone.now() + timedelta(minutes=validity_minutes),created_by=created_by,)



SIMULATED_GATEWAY_NAME = "Simulated Gateway"
 
 
class NothingToPayError(Exception):
    pass
 
 
class InvalidPaymentAttempt(Exception):
    pass 

class PaymentAttemptExpired(Exception):
    pass
 
 
def _generate_transaction_id():
    return f"TXN{uuid.uuid4().hex[:14].upper()}"
 
 
@transaction.atomic
def initiate_online_payment(invoice, created_by=None, validity_minutes=30):
    balance = invoice.balance_due
    if balance <= 0:
        raise NothingToPayError()
    old_links = list(PaymentGatewayLink.objects.select_for_update().filter(invoice=invoice, status="active"))
    if old_links:
        PaymentHistory.objects.filter(gateway_link__in=old_links, callback_status="pending", is_callback_updated=False).update(callback_status="cancelled", link_status="inactive", updated_at=timezone.now())
 
        PaymentGatewayLink.objects.filter(id__in=[l.id for l in old_links]).update(status="inactive", updated_at=timezone.now())
    transaction_id = _generate_transaction_id()
    link = PaymentGatewayLink.objects.create(invoice=invoice,student=invoice.student,token=f"SIM-{transaction_id}-{uuid.uuid4().hex[:10]}",amount=balance,expires_at=timezone.now() + timedelta(minutes=validity_minutes),created_by=created_by,)
    return PaymentHistory.objects.create(gateway_link=link,invoice=invoice,student=invoice.student,transaction_id=transaction_id,gateway_name=SIMULATED_GATEWAY_NAME,amount=balance,link_status="active",callback_status="pending",)
 
 
 
@transaction.atomic
def _get_or_create_open_settlement_batch(college):
    
    now = timezone.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    batch = (SettlementBatch.objects.select_for_update().filter(college=college, status="pending", period_from=day_start, period_to=day_end).first())
    if batch:
        return batch
 
    return SettlementBatch.objects.create(college=college,status="pending",period_from=day_start,period_to=day_end,)
 
 
@transaction.atomic
def queue_payment_for_settlement(fee_payment):
    college = fee_payment.invoice.college
    batch = _get_or_create_open_settlement_batch(college)
    item, created = SettlementBatchItem.objects.get_or_create(fee_payment=fee_payment,defaults={"batch": batch, "amount": fee_payment.amount},)
    if created:
        batch.recompute_totals()
 
    return item
 
 
@transaction.atomic
def process_mock_gateway_callback(transaction_id, result, payment_mode, student):
   
    try:
        history = PaymentHistory.objects.select_related("invoice", "gateway_link").get(transaction_id=transaction_id, student=student)
    except PaymentHistory.DoesNotExist:
        raise InvalidPaymentAttempt()
 
    if history.is_callback_updated:
        return history
 
    now = timezone.now()
    invoice = history.invoice
    payment_status = "success" if result == "success" else "failed"
 
    payment = FeePayment.objects.create(invoice=invoice,student=student,payment_type="online",payment_mode=payment_mode,amount=history.amount,gateway_name=history.gateway_name,gateway_transaction_id=history.transaction_id,status=payment_status,paid_at=now if payment_status == "success" else None,)
    history.callback_status = payment_status
    history.gateway_transaction_id = history.transaction_id
    history.callback_raw_response = {"simulated": True,"result": result,"payment_mode": payment_mode,"received_at": now.isoformat(),}
    history.callback_received_at = now
    history.is_callback_updated = True
    history.fee_payment = payment
    history.link_status = "consumed" if payment_status == "success" else "inactive"
    history.save(update_fields=["callback_status", "gateway_transaction_id", "callback_raw_response","callback_received_at", "is_callback_updated", "fee_payment","link_status", "updated_at",])
 
    history.gateway_link.status = "consumed" if payment_status == "success" else "inactive"
    history.gateway_link.save(update_fields=["status", "updated_at"])
 
    if payment_status == "success":
        invoice.refresh_status()
        queue_payment_for_settlement(payment)
 
    return history