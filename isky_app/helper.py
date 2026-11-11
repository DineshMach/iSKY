from collections import defaultdict
import datetime
import re
import uuid,hashlib,secrets
from django.db import models
from django.db.models import Q, DecimalField, Sum
from django.db.models.functions import Coalesce
from django.http import Http404
from datetime import date, time
from django.utils import timezone
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from user_agents import parse
from .models import YEAR_CHOICES,DepartmentSubjectMapping, AcademicYear, Classroom, Department, FeeConcession, FeePayment, MeritScholarshipSlab, PaymentGatewayLink, PaymentHistory, PeriodAttendanceSession, SettlementBatch, SettlementBatchItem, StaffProfile, StudentAttendance, StudentEnrollment, StudentFeeInvoice, StudentFeeInvoiceItem, StudentProfile, TimetableSlot
#Get device information
from .models import CollegeUser  # Import your user detail / profile model
from decimal import Decimal
from django.shortcuts import get_object_or_404, render
from rest_framework import serializers
from django.db import IntegrityError, transaction, models as dj_models
from django.db.models import Q, Exists, OuterRef


DAYS_OF_WEEK = [(1, "Monday"), (2, "Tuesday"), (3, "Wednesday"), (4, "Thursday"), (5, "Friday"), (6, "Saturday")]
DEFAULT_PERIOD_LENGTH_MINUTES = 50
DEFAULT_FIRST_PERIOD_START = time(9, 0)

PRESENT_STATUSES = ["P", "L", "OD"]  # what counts as "present" in percentages


def _compute_payment_status(student):
    invoices = getattr(student, "active_invoices", [])
    if not invoices:
        return "unpaid", Decimal("0"), Decimal("0")

    total_due = sum((inv.total_amount - inv.discount_amount) for inv in invoices)
    total_paid = sum(sum(p.amount for p in inv.payments.all()) for inv in invoices)

    if total_paid <= 0:
        status_ = "unpaid"
    elif total_paid < total_due:
        status_ = "partial"
    else:
        status_ = "paid"
    return status_, total_due, total_paid


def _sort_students(students):
    students.sort(key=lambda s: s.roll_number or "")
    students.sort(key=lambda s: s.semester or 0)
    students.sort(key=lambda s: s.year or 0)
    students.sort(key=lambda s: s.academic_year or "", reverse=True)
    return students


def user_details(request):
    if not request.user.is_authenticated:
        return {"user_profile": None, "user_role": None}
    profile = (CollegeUser.objects.filter(user=request.user, status="active").select_related("user", "college").first())
    return {"user_profile": profile,"user_role": profile.role if profile else None,"user_college": profile.college if profile else None,}

def get_device_info(request):
    user_agent_string = request.META.get("HTTP_USER_AGENT","")
    print(user_agent_string)
    user_agent = parse(user_agent_string)
    browser = user_agent.browser.family or "Unknown"
    operating_system = user_agent.os.family or "Unknown"
    if user_agent.is_mobile:
        device_type = "mobile"
    elif user_agent.is_tablet:
        device_type = "tablet"
    elif user_agent.is_pc:
        device_type = "desktop"
    else:
        device_type = "unknown"

    device_name = f"{operating_system} - {browser}"

    return {
        "browser": browser,
        "operating_system": operating_system,
        "device_type": device_type,
        "device_name": device_name,
        "user_agent": user_agent_string,
    }
    
#get ip address
    
def get_client_ip(request):

    # IMPORTANT:
    # Only use X-Forwarded-For when it comes from
    # a trusted reverse proxy such as your configured Nginx.
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")

    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR")

def hash_device_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

from decimal import Decimal
from django.utils import timezone


FIRST_GENERATION_GRADUATE_DEFAULT_PERCENTAGE = Decimal("20")


def sync_student_fee_concessions(student, today=None):
    """
    Create/update automatic FeeConcession records based on
    the student's eligibility.

    Merit scholarship:
        Uses MeritScholarshipSlab.

    First generation graduate:
        Uses FIRST_GENERATION_GRADUATE_DEFAULT_PERCENTAGE.

    These concessions are blanket concessions because category=None.
    """

    today = today or timezone.now().date()

    # ---------------------------------------------------------
    # 1. MERIT SCHOLARSHIP
    # ---------------------------------------------------------
    merit_slab = None

    if student.qualifying_marks_percentage is not None:

        merit_slab = (
            MeritScholarshipSlab.objects
            .filter(
                college_id=student.college_id,
                is_active=True,
                min_percentage__lte=student.qualifying_marks_percentage,
                max_percentage__gte=student.qualifying_marks_percentage,
            )
            .order_by("-waiver_percentage")
            .first()
        )

    if merit_slab:
        student.is_merit_scholarship = True

        FeeConcession.objects.update_or_create(
            student=student,
            category=None,
            reason="merit_scholarship",
            defaults={
                "reason_detail": (
                    f"{merit_slab.label} - "
                    f"{student.qualifying_marks_percentage}% qualifying marks"
                ),
                "concession_type": "percentage",
                "value": merit_slab.waiver_percentage,
                "is_recurring": True,
                "valid_from": today,
                "valid_until": None,
                "is_active": True,
            },
        )

    else:
        student.is_merit_scholarship = False

        # Disable old automatic merit concession
        FeeConcession.objects.filter(
            student=student,
            category=None,
            reason="merit_scholarship",
        ).update(
            is_active=False,
            updated_at=timezone.now(),
        )

    # ---------------------------------------------------------
    # 2. FIRST GENERATION GRADUATE
    # ---------------------------------------------------------

    if student.is_first_generation_graduate:

        FeeConcession.objects.update_or_create(
            student=student,
            category=None,
            reason="first_generation_graduate",
            defaults={
                "reason_detail": "First Generation Graduate",
                "concession_type": "percentage",
                "value": FIRST_GENERATION_GRADUATE_DEFAULT_PERCENTAGE,
                "is_recurring": True,
                "valid_from": today,
                "valid_until": None,
                "is_active": True,
            },
        )

    else:
        # Disable old automatic first-generation concession
        FeeConcession.objects.filter(
            student=student,
            category=None,
            reason="first_generation_graduate",
        ).update(
            is_active=False,
            updated_at=timezone.now(),
        )

    student.save(
        update_fields=[
            "is_merit_scholarship",
            "updated_at",
        ]
    )
    
    

# ---------------------------------------------------------------------------
# Helper (service functions, not models)
# ---------------------------------------------------------------------------

def generate_invoices_for_structure(fee_structure, semester=None, due_date=None):
    """
    fee_structure: FeeStructure instance
    semester: required if fee_structure.billing_cycle == 'semester'
    due_date: date the invoice is due; defaults to 30 days from now
    """
    from datetime import timedelta
    due_date = due_date or (timezone.now().date() + timedelta(days=30))
    students_qs = StudentProfile.objects.filter(college=fee_structure.college, year=fee_structure.year, is_active=True,)
    if fee_structure.department:
        students_qs = students_qs.filter(department=fee_structure.department)

    items_qs = fee_structure.items.filter(is_active=True)
    if fee_structure.billing_cycle == "semester":
        items_qs = items_qs.filter(models.Q(semester=semester) | models.Q(semester__isnull=True))

    created_invoices = []
    for student in students_qs:
        invoice, created = StudentFeeInvoice.objects.get_or_create(student=student, fee_structure=fee_structure, semester=semester,defaults={"academic_year": fee_structure.academic_year,"due_date": due_date,"total_amount": 0,},)
        if not created:
            continue  # already generated for this student/structure/semester
        
        today = timezone.now().date()
        # Pull this student's live concessions once, so a merit scholarship
        # granted after last semester (or one that lapsed because marks
        # dropped / is_active was turned off) is picked up correctly here —
        # concessions are never edited onto old, already-generated invoices.
        concessions = list(FeeConcession.objects.filter(student=student, is_active=True))
        def concession_for(category):
            applicable = [
                c for c in concessions
                if c.is_applicable_on(today) and (c.category_id is None or c.category_id == category.id)
            ]
            if not applicable:
                return None
            # If more than one concession matches a category, take the one
            # that saves the student the most rather than silently stacking
            # them — stacking should be an explicit, separate decision.
            return max(applicable, key=lambda c: c.amount_off(1))
        
        total = 0
        total_concession = 0
        for item in items_qs:
            if item.category.is_optional:
                continue  # optional categories (e.g. Hostel) need an explicit opt-in step, not auto-billed
            StudentFeeInvoiceItem.objects.create(invoice=invoice, category=item.category, amount=item.amount)
            concession = concession_for(item.category)
            discount = concession.amount_off(item.amount) if concession else 0
            net_amount = item.amount - discount
            total += item.amount
            total_concession += discount
        invoice.total_amount = total
        invoice.discount_amount = total_concession
        invoice.discount_reason = "Fee concession(s) applied" if total_concession else ""
        invoice.save(update_fields=["total_amount", "discount_amount", "discount_reason"])
        created_invoices.append(invoice)

    return created_invoices


 
def promote_or_graduate_student(student, new_year=None, new_semester=None, graduate=False):
    """
    Year-end batch helper. Either advances a student to the next
    year/semester (so future generate_invoices_for_structure runs pick up
    the new FeeStructure), or marks them graduated/dropped so
    generate_invoices_for_structure's is_active=True filter stops billing
    them entirely. Does NOT touch invoices already generated for prior terms.
    """
    if graduate:
        student.status = "graduated"
        student.graduation_date = timezone.now().date()
        student.save(update_fields=["status", "graduation_date", "is_active", "updated_at"])
        return student
 
    if new_year is not None:
        student.year = new_year
    if new_semester is not None:
        student.semester = new_semester
    student.save(update_fields=["year", "semester", "updated_at"])
    return student
 
 
def grant_fee_concession(student, reason, concession_type, value, category=None,is_recurring=False, valid_from=None, valid_until=None, approved_by=None):
    
    return FeeConcession.objects.create(
        student=student,
        category=category,
        reason=reason,
        concession_type=concession_type,
        value=value,
        is_recurring=is_recurring,
        valid_from=valid_from or timezone.now().date(),
        valid_until=valid_until,
        approved_by=approved_by,
        approved_at=timezone.now() if approved_by else None,
    )
 
 
def grant_first_generation_graduate_concession(student, value, concession_type="percentage",eligible_departments=None, approved_by=None):
    if not getattr(student, "is_first_generation_graduate", False):
        raise ValueError("Student is not flagged is_first_generation_graduate=True.")
 
    if eligible_departments is not None:
        eligible_ids = {d.id for d in eligible_departments}
        if student.department_id not in eligible_ids:
            raise ValueError("Student's department is not eligible for this scheme.")
 
    # Replace any existing one rather than stacking a duplicate if re-run.
    FeeConcession.objects.filter(student=student, reason="first_generation_graduate", is_active=True, category__isnull=True,).update(is_active=False)
 
    return FeeConcession.objects.create(
        student=student,
        category=None,
        reason="first_generation_graduate",
        reason_detail="First generation graduate — Engineering fee deduction"
                       if eligible_departments is not None else "First generation graduate",
        concession_type=concession_type,
        value=value,
        is_recurring=True,
        valid_from=timezone.now().date(),
        valid_until=None,
        approved_by=approved_by,
        approved_at=timezone.now() if approved_by else None,
    )
 
 
def auto_grant_merit_scholarship(student, approved_by=None):
    
    if student.qualifying_marks_percentage is None:
        raise ValueError("Student has no qualifying_marks_percentage set; nothing to match against.")
    slabs = MeritScholarshipSlab.objects.filter(college=student.college, is_active=True)
    slab = next((s for s in slabs if (not s.admission_academic_year or s.admission_academic_year == student.academic_year)and s.matches(student.qualifying_marks_percentage)),None,)
    if slab is None:
        return None  # marks don't fall into any configured scholarship band — full fees apply
 
    # Replace any existing auto-granted merit scholarship rather than
    # stacking a second one if this is re-run (e.g. marks were corrected).
    FeeConcession.objects.filter(student=student, reason="merit_scholarship", is_active=True, category__isnull=True,).update(is_active=False)
    # applies to the whole invoice
    return FeeConcession.objects.create(student=student,category=None,reason="merit_scholarship",reason_detail=f"{slab.label} ({student.qualifying_marks_percentage}% qualifying marks)",concession_type="percentage",value=slab.waiver_percentage,is_recurring=True,valid_from=timezone.now().date(),valid_until=None,approved_by=approved_by,approved_at=timezone.now() if approved_by else None,)
  

def generate_payment_gateway_link(invoice, created_by=None, validity_minutes=30):
    """
    Creates a fresh PaymentGatewayLink for an invoice's outstanding balance.
    Any previously active link for the same invoice is flipped to 'inactive'
    first, so there is never more than one usable link at a time
    (enforced at the DB level by unique_active_gateway_link_per_invoice too).
    """
    from datetime import timedelta
    balance = invoice.balance_due
    if balance <= 0:
        raise ValueError("Invoice has no outstanding balance; nothing to generate a link for.")
    PaymentGatewayLink.objects.filter(invoice=invoice, status="active").update(status="inactive", updated_at=timezone.now())
    return PaymentGatewayLink.objects.create(invoice=invoice,student=invoice.student,token=secrets.token_urlsafe(32),amount=balance,expires_at=timezone.now() + timedelta(minutes=validity_minutes),created_by=created_by,)


def start_payment_attempt(gateway_link, gateway_name):
    """
    Called when the student lands on the link and the gateway checkout is
    initiated. Creates the PaymentHistory row that the eventual callback
    will be matched against via transaction_id.
    """
    if not gateway_link.is_usable:
        raise ValueError("This payment link is no longer active or has expired.")
    return PaymentHistory.objects.create(gateway_link=gateway_link,invoice=gateway_link.invoice,student=gateway_link.student,transaction_id=f"TXN-{uuid.uuid4().hex[:14].upper()}",gateway_name=gateway_name,amount=gateway_link.amount,link_status=gateway_link.status,)


def record_gateway_callback(transaction_id, raw_response, callback_status,gateway_transaction_id="", gateway_order_id=""):
    """
    Webhook/callback entry point. Idempotent: replays of the same callback
    (transaction_id already processed) are a no-op thanks to
    is_callback_updated, so the gateway can safely retry delivery.
    """
    try:
        history = PaymentHistory.objects.select_related("invoice", "gateway_link", "student").get(transaction_id=transaction_id)
    except PaymentHistory.DoesNotExist:
        raise ValueError(f"No PaymentHistory found for transaction_id={transaction_id}")

    history.callback_raw_response = raw_response
    history.callback_status = callback_status
    history.callback_received_at = timezone.now()
    if gateway_transaction_id:
        history.gateway_transaction_id = gateway_transaction_id
    if gateway_order_id:
        history.gateway_order_id = gateway_order_id

    if history.is_callback_updated:
        # Already processed once (e.g. a duplicate webhook delivery) — just
        # persist the latest raw payload for audit, don't double-credit.
        history.save(update_fields=["callback_raw_response", "callback_status", "callback_received_at","gateway_transaction_id", "gateway_order_id", "updated_at",])
        return history

    if callback_status == "success":
        payment = FeePayment.objects.create(invoice=history.invoice,student=history.student,payment_type="online",payment_mode="upi",amount=history.amount,gateway_name=history.gateway_name,gateway_transaction_id=history.gateway_transaction_id,gateway_order_id=history.gateway_order_id,status="success",paid_at=timezone.now(),)  # replace with the actual mode reported by the gateway payload if available
        history.fee_payment = payment
        history.gateway_link.status = "consumed"
        history.gateway_link.save(update_fields=["status", "updated_at"])
        history.invoice.refresh_status()
    elif callback_status in ("failed", "cancelled"):
        history.gateway_link.status = "active"  # leave link usable for a retry, unless separately expired
        history.gateway_link.save(update_fields=["status", "updated_at"])

    history.is_callback_updated = True
    history.link_status = history.gateway_link.status
    history.save(update_fields=["callback_raw_response", "callback_status", "callback_received_at","gateway_transaction_id", "gateway_order_id", "fee_payment","is_callback_updated", "link_status", "updated_at",])
    return history


def create_settlement_batch(college, period_from, period_to, initiated_by=None):
    unsettled_payments = FeePayment.objects.filter(invoice__fee_structure__college=college,status="success",paid_at__gte=period_from,paid_at__lt=period_to,settlement_item__isnull=True,)
    if not unsettled_payments.exists():
        return None

    batch = SettlementBatch.objects.create(college=college,period_from=period_from,period_to=period_to,initiated_by=initiated_by,status="pending",)
    SettlementBatchItem.objects.bulk_create([SettlementBatchItem(batch=batch, fee_payment=payment, amount=payment.amount)
        for payment in unsettled_payments
    ])
    batch.recompute_totals()
    return batch


def mark_batch_settled(batch, settled_fee_payment_ids=None, failed_fee_payment_ids=None):
    items = batch.items.select_related("fee_payment")
    if settled_fee_payment_ids is None and failed_fee_payment_ids is None:
        for item in items:
            item.mark_settled()
    else:
        settled_fee_payment_ids = set(settled_fee_payment_ids or [])
        failed_fee_payment_ids = set(failed_fee_payment_ids or [])
        for item in items:
            if item.fee_payment_id in settled_fee_payment_ids:
                item.mark_settled()
            elif item.fee_payment_id in failed_fee_payment_ids:
                item.failure_reason = "Payout rejected by bank/partner"
                item.save(update_fields=["failure_reason", "updated_at"])

    batch.status = "processing" if batch.status == "pending" else batch.status
    batch.save(update_fields=["status", "updated_at"])
    batch.refresh_status()
    return batch


def _get_college_user(request):
    return get_object_or_404(CollegeUser.objects.select_related("college"), user=request.user)
 
 
def _get_object_or_404_uuid(qs, **kwargs):
    try:
        return get_object_or_404(qs, **kwargs)
    except (DjangoValidationError, ValueError):
        raise Http404("Invalid id.")
 
 
def _resolve_academic_year(request, college):
    qs = AcademicYear.objects.filter(college=college)
    ay_id = request.GET.get("academic_year")
    if ay_id:
        return _get_object_or_404_uuid(qs, id=ay_id)
    return qs.filter(is_current=True).first() or qs.order_by("-start_date").first()
 
 
def _get_classroom_and_year(request, college):
    classroom_id = request.GET.get("classroom")
    if classroom_id:
        classroom = _get_object_or_404_uuid(
            Classroom.objects.select_related("academic_year", "department"),
            id=classroom_id, college=college,
        )
        return classroom, classroom.academic_year
    return None, _resolve_academic_year(request, college)
 
 
def _default_period_time(period_number):
    start_minutes = (period_number - 1) * DEFAULT_PERIOD_LENGTH_MINUTES
    today = datetime.date.today()
    start = (datetime.datetime.combine(today, DEFAULT_FIRST_PERIOD_START)
             + datetime.timedelta(minutes=start_minutes)).time()
    end = (datetime.datetime.combine(today, start)
           + datetime.timedelta(minutes=DEFAULT_PERIOD_LENGTH_MINUTES)).time()
    return start, end
 
 
def _get_editable_slot_ids(request_user, college_user, classroom, weekday, all_slots):
    if not classroom.academic_year.is_current:
        return set()
 
    all_ids = {s.id for s in all_slots}
 
    if college_user.role in ("master_admin", "office_admin"):
        return all_ids
 
    staff_profile = (StaffProfile.objects.filter(college_user=college_user, is_active=True).select_related("department").first())
    if not staff_profile:
        return set()
 
    if staff_profile.staff_role == "hod" and staff_profile.department_id == classroom.department_id:
        return all_ids
 
    if staff_profile.staff_role == "class_advisor":
        # TODO: restrict to the advisor's own department + advisor_year
        # (staff_profile.department_id == classroom.department_id and staff_profile.advisor_year == classroom.year)
        return all_ids
 
    return {s.id for s in all_slots if s.teacher_id == request_user.id}
 
 
@transaction.atomic
def enroll_student(student, classroom, roll_number=""):
    # close any currently active enrollment
    StudentEnrollment.objects.filter(student=student, is_active=True).exclude(classroom=classroom).update(is_active=False)

    enrollment, created = StudentEnrollment.objects.get_or_create(
        student=student, classroom=classroom,
        defaults={"roll_number": roll_number or student.roll_number},
    )
    if not enrollment.is_active:
        enrollment.is_active = True
        enrollment.save()

    # keep the profile's cached "current" fields in sync
    student.department_id = classroom.department_id
    student.year = classroom.year
    student.semester = classroom.semester
    student.section = classroom.section
    student.save(update_fields=["department", "year", "semester", "section", "updated_at"])
    return enrollment


def find_classroom(student):
    ay = AcademicYear.objects.filter(college=student.college, is_current=True).first()
    return Classroom.objects.filter(
        college=student.college, academic_year=ay, department=student.department,
        year=student.year, semester=student.semester, section=student.section or "",
    ).first()
    
    
class EnrollmentConflict(Exception):
    pass


def resolve_target_academic_year(college, name):
    """No name -> current year. Unknown name -> created, with dates shifted from the latest year."""
    if not name:
        return AcademicYear.objects.filter(college=college, is_current=True).first()

    existing = AcademicYear.objects.filter(college=college, name=name).first()
    if existing:
        return existing

    start_year, end_year = int(name[:4]), int(name[5:])
    if end_year != start_year + 1:
        raise serializers.ValidationError({"academic_year": "Academic year must span two consecutive years, e.g. 2026-2027."})

    latest = AcademicYear.objects.filter(college=college).order_by("-start_date").first()
    if latest:
        span = latest.end_date.year - latest.start_date.year
        start = date(start_year, latest.start_date.month, min(latest.start_date.day, 28))
        end = date(start_year + span, latest.end_date.month, min(latest.end_date.day, 28))
    else:
        start, end = date(start_year, 6, 1), date(end_year, 5, 31)
    return AcademicYear.objects.create(college=college, name=name, start_date=start, end_date=end, is_current=False)


def get_or_create_classroom(college, academic_year, department, year, semester, section):
    label = f"Section {section}" if section else f"Year {year}"
    return Classroom.objects.get_or_create(
        college=college, academic_year=academic_year, department=department,
        year=year, semester=semester, section=section,
        defaults={"name": f"{department.short_name or department.code} - {label}"[:50]},
    )  # -> (classroom, created)


@transaction.atomic
def enroll_students(student, classroom, roll_number=""):
    # a student may only have one enrollment per (academic year, semester)
    same_term = StudentEnrollment.objects.filter(
        student=student, academic_year_id=classroom.academic_year_id, semester=classroom.semester).first()

    # close every other active enrollment: this is the history, we never edit its classroom
    StudentEnrollment.objects.filter(student=student, status="active").exclude(
        pk=same_term.pk if same_term else None
    ).update(status="completed", is_active=False, ended_on=timezone.localdate())   # drop is_active once the field is removed

    if same_term:
        if same_term.classroom_id != classroom.id:
            # section change inside the same term: only safe if nothing was recorded yet
            if StudentAttendance.objects.filter(student=student, session__timetable_slot__classroom=same_term.classroom).exists():
                raise EnrollmentConflict("already has attendance in this term's current section")
            same_term.classroom = classroom
        same_term.status, same_term.is_active, same_term.ended_on = "active", True, None
        same_term.save()
        enrollment = same_term
    else:
        enrollment = StudentEnrollment.objects.create(
            student=student, classroom=classroom, roll_number=roll_number or student.roll_number)

    student.department_id = classroom.department_id
    student.year, student.semester, student.section = classroom.year, classroom.semester, classroom.section
    student.save(update_fields=["department", "year", "semester", "section", "updated_at"])
    return enrollment

def classroom_is_open(classroom):
    return classroom.is_active

def next_term(classroom):
    sem = classroom.semester + 1
    return (sem + 1) // 2, sem            # (year, semester)


@transaction.atomic
def upgrade_classroom(classroom, enrollment_ids=None, academic_year_name=None):
    if not classroom.is_active:
        raise serializers.ValidationError("This classroom is already closed.")
    college, today = classroom.college, timezone.localdate()

    active = classroom.enrollments.filter(status="active").select_related("student")
    chosen = active.filter(id__in=enrollment_ids) if enrollment_ids is not None else active
    chosen = list(chosen)
    chosen_ids = {e.id for e in chosen}

    # students left out of the upgrade (e.g. failed) are marked detained, not moved
    for e in active:
        if e.id not in chosen_ids:
            e.status, e.ended_on = "detained", today
            e.save()

    target = None
    if classroom.semester >= 8:                        # final semester: graduate
        for e in chosen:
            e.status, e.ended_on = "completed", today
            e.save()
            e.student.status, e.student.graduation_date = "graduated", today
            e.student.save(update_fields=["status", "graduation_date", "updated_at"])
    else:
        year, sem = next_term(classroom)
        if sem % 2 == 0:                               # odd -> even: same academic year
            target_ay = classroom.academic_year
        else:                                          # even -> odd: next academic year
            if not academic_year_name:
                raise serializers.ValidationError({"academic_year": "Enter the next academic year, e.g. 2026-2027."})
            target_ay = resolve_target_academic_year(college, academic_year_name)
            if target_ay.id == classroom.academic_year_id:
                raise serializers.ValidationError({"academic_year": "Choose the next academic year, not the current one."})
        target, _ = get_or_create_classroom(college, target_ay, classroom.department, year, sem, classroom.section)
        for e in chosen:
            enroll_student(e.student, target)          # closes the old enrollment, keeps history

    classroom.is_active, classroom.closed_on = False, today
    classroom.save(update_fields=["is_active", "closed_on"])
    return target, len(chosen)




ADMIN_ROLES = ("master_admin", "office_admin", "finance_admin", "staff_admin")
OTP_TTL = 10 * 60          # seconds
OTP_MAX_ATTEMPTS = 5
 
 
# ---------------------------------------------------------------- helpers
def get_membership(user):
    """The logged-in user's admin/staff CollegeUser row (None if they have none)."""
    return (
        CollegeUser.objects
        .filter(user=user, role__in=ADMIN_ROLES, status="active")
        .select_related("user", "college", "staff_profile", "staff_profile__department")
        .order_by("-joined_at")
        .first()
    )
 
 
def build_profile(m):
    """Flat dict for the templates. Works for admins (no StaffProfile) and staff."""
    u = m.user
    sp = getattr(m, "staff_profile", None)

    dept = ""
    if sp and sp.department:
        dept = sp.department.name
    elif m.department and m.department != "No Access":
        dept = m.department

    if sp and sp.department_id:
        dept_id = sp.department_id
    else:
        dept_id = (Department.objects.filter(college=m.college, name=m.department)
                   .values_list("id", flat=True).first())

    exp = re.match(r"\s*(\d{1,2}(?:\.\d)?)", m.work_experience or "")

    return {
        "full_name": u.get_full_name() or u.get_username(),
        "email": u.email,
        "mobile_number": getattr(u, "mobile_number", "") or "",
        "role": m.get_role_display(),
        "role_raw": m.role,
        "status": m.get_status_display(),
        "college_name": m.college.name,
        "department_name": dept,
        "department_id": dept_id,
        "experience_years": exp.group(1) if exp else "",
        "employee_id": m.employee_or_student_id,
        "date_of_birth": m.date_of_birth,
        "blood_group": m.blood_group or "",
        "emergency_contact_number": m.emergency_contact_number or "",
        "address": m.address or "",
        "work_experience": m.work_experience,
        "joined_at": m.joined_at,
        "is_staff_profile": sp is not None,
        "staff_role": sp.get_staff_role_display() if sp else "",
        "staff_role_raw": sp.staff_role if sp else "",
        "advisor_year": sp.advisor_year if sp else None,
        "designation": sp.designation if sp else "",
        "joining_date": sp.joining_date if sp else None,
    }
    
    
def mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"
 
 
def _otp_key(user):
    return f"admin-pw-otp:{user.pk}"
 
 
def _hash_otp(user, otp):
    return hashlib.sha256(f"{user.pk}:{otp}".encode()).hexdigest()



# ===== Classroom Access =======

FULL_ROLES = ("master_admin", "office_admin")

def get_classroom_access(college_user):
    base = {"level": "none", "department": None, "year": None, "staff": None,"can_create": False, "can_manage_academic_years": False}
 
    if college_user.role in FULL_ROLES:
        return {**base, "level": "full", "can_create": True, "can_manage_academic_years": True}
 
    staff = (StaffProfile.objects.filter(college_user=college_user, is_active=True, department__isnull=False).select_related("department").first())
    if not staff:
        return base
 
    common = {**base, "department": staff.department, "staff": staff}
    if staff.staff_role == "hod":
        return {**common, "level": "department", "can_create": True}
    if staff.staff_role == "class_advisor" and staff.advisor_year:
        return {**common, "level": "class", "year": staff.advisor_year}
    if staff.staff_role == "staff":
        return {**common, "level": "teaching"}
    return base
 
 
def scope_classrooms(qs, access, user):
    level = access["level"]
    if level == "full":
        return qs
    if level == "none":
        return qs.none()

    staff = access["staff"]

    qs = qs.annotate(
        _taught_by_slot=Exists(
            TimetableSlot.objects.filter(classroom=OuterRef("pk"), teacher=user)
        ),
        _taught_by_mapping=Exists(
            DepartmentSubjectMapping.objects.filter(
                teacher=staff,
                department_id=OuterRef("department_id"),
                year=OuterRef("year"),
                semester=OuterRef("semester"),
                # academic_year=OuterRef("academic_year"),  # if the mapping has it
            )
        ),
    )
    taught = Q(_taught_by_slot=True) | Q(_taught_by_mapping=True)

    if level == "department":      # HOD: own department + anything they teach
        return qs.filter(Q(department=access["department"]) | taught)
    if level == "class":           # advisor: own class + anything they teach
        return qs.filter(Q(department=access["department"], year=access["year"]) | taught)
    if level == "teaching":
        return qs.filter(taught)
    return qs.none()
 
 
def creatable_departments(college, access):
    """Departments this user may create classrooms in."""
    qs = Department.objects.filter(is_active=True, college=college).order_by("name")
    if access["level"] == "full":
        return qs
    if access["level"] == "department":
        return qs.filter(id=access["department"].id)
    return qs.none()
 
 
def visible_departments(college, access, classrooms_qs=None):
    depts = Department.objects.filter(college=college)
    if access["level"] == "full":
        return depts
    if access["level"] in ("department", "class"):
        # class advisors may also teach in other depts
        if classrooms_qs is not None:
            return depts.filter(Q(pk=access["department"].pk) | Q(pk__in=classrooms_qs.values("department_id")))
        return depts.filter(pk=access["department"].pk)
    if access["level"] == "teaching" and classrooms_qs is not None:
        return depts.filter(pk__in=classrooms_qs.values("department_id"))
    return depts.none()
 
 
def valid_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None
 
 
 

# Flip to True if a HOD who personally teaches a period should be able to mark it.
HOD_CAN_MARK_OWN_PERIODS = False
 
 
def get_staff_profile(college_user):
    return (
        StaffProfile.objects
        .filter(college_user=college_user, is_active=True)
        .select_related("department").first()
    )
 
 
def get_schedule_access(college_user):
    base = {"level": "none", "role": None, "staff": None, "department": None,
            "year": None, "can_enroll": False}
 
    if college_user.role in FULL_ROLES:
        return {**base, "level": "full", "role": college_user.role, "can_enroll": True}
 
    staff = get_staff_profile(college_user)
    if not staff:
        return base
 
    return {
        **base,
        "level": "staff",
        "role": staff.staff_role,
        "staff": staff,
        "department": staff.department,
        "year": staff.advisor_year if staff.staff_role == "class_advisor" else None,
        "can_enroll": staff.staff_role == "hod" and staff.department_id is not None,
    }
 
 
# ---------------------------------------------------------------------------
# Who "takes" a period
#   If the slot names a teacher, that teacher owns it; otherwise fall back to
#   the subject mapping's teacher.
# ---------------------------------------------------------------------------
def is_my_slot(slot, user, staff):
    if slot.teacher_id:
        return slot.teacher_id == user.id
    mapping = slot.subject_mapping
    return bool(staff and mapping and mapping.teacher_id == staff.id)
 
 
def _teaching_q(user, staff):
    q = Q(timetable_slots__teacher=user)
    if staff:
        q |= Q(timetable_slots__teacher__isnull=True,
               timetable_slots__subject_mapping__teacher=staff)
    return q
 
 
# ---------------------------------------------------------------------------
# Classroom scoping
# ---------------------------------------------------------------------------
def scope_schedule_classrooms(qs, access, user):
    """Classrooms whose timetable / attendance this user may SEE."""
    if access["level"] == "full":
        return qs
    if access["level"] == "none":
        return qs.none()
 
    q = _teaching_q(user, access["staff"])
    dept_id = access["department"].id if access["department"] else None
    if access["role"] == "hod" and dept_id:
        q |= Q(department_id=dept_id)
    if access["role"] == "class_advisor" and dept_id and access["year"]:
        q |= Q(department_id=dept_id, year=access["year"])
    return qs.filter(q).distinct()
 
 
def editable_timetable_classrooms(qs, access):
    """Classrooms whose timetable this user may EDIT."""
    if access["level"] == "full":
        return qs
    if access["role"] == "hod" and access["department"]:
        return qs.filter(department=access["department"])
    return qs.none()
 
 
def can_edit_timetable_for(access, classroom):
    if access["level"] == "full":
        return True
    return bool(access["role"] == "hod" and access["department"]
                and classroom.department_id == access["department"].id)
 
 
# ---------------------------------------------------------------------------
# Attendance: which slots may this user update?
# ---------------------------------------------------------------------------
def editable_attendance_slot_ids(user, college_user, classroom, all_slots):
    if not classroom.is_active:
        return set()
 
    staff = get_staff_profile(college_user)
    if not staff:
        return set()                     # admins and everyone else: no attendance updates
 
    role = staff.staff_role
 
    # Class advisor: every period of their own class
    if (role == "class_advisor" and staff.advisor_year
            and staff.department_id == classroom.department_id
            and staff.advisor_year == classroom.year):
        return {s.id for s in all_slots}
 
    # Staff (and advisors, for classes that aren't theirs): only periods they teach
    if role in ("staff", "class_advisor") or (role == "hod" and HOD_CAN_MARK_OWN_PERIODS):
        return {s.id for s in all_slots if is_my_slot(s, user, staff)}
 
    return set()


 
def get_promotion_access(college_user):
    none = {"level": "none", "department": None, "year": None,
            "target_years": [], "can_create_academic_year": False}
 
    if college_user.role in FULL_ROLES:
        return {**none, "level": "full", "target_years": list(YEAR_CHOICES),
                "can_create_academic_year": True}
 
    staff = get_staff_profile(college_user)
    if (staff and staff.staff_role == "class_advisor"
            and staff.department_id and staff.advisor_year):
        allowed = {staff.advisor_year, staff.advisor_year + 1}
        return {**none, "level": "class", "department": staff.department,
                "year": staff.advisor_year,
                "target_years": [(v, l) for v, l in YEAR_CHOICES if v in allowed]}
 
    return none
 
 
def scope_promotion_students(qs, access):
    if access["level"] == "class":
        return qs.filter(department=access["department"], year=access["year"])
    if access["level"] == "none":
        return qs.none()
    return qs



def _display_name(user):
    return user.get_full_name().strip() or user.username
 
 
def _get_scoped_classroom(request, college_user, classroom_id):
    """Fetch the classroom only if this user is allowed to see it."""
    access = get_classroom_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have access to classrooms.")
    qs = scope_classrooms(Classroom.objects.filter(college=college_user.college, id=classroom_id).select_related("department", "academic_year"),access,request.user,)
    return access, get_object_or_404(qs)
 
 
def _can_manage_classroom(access, classroom):
    """Full / department-level users, current academic year only."""
    return (
        access["level"] in ("full", "department")
        and classroom.academic_year is not None
        and classroom.academic_year.is_current
    )
 
 
def _is_class_advisor(college_user, classroom):
    """True only for the active class advisor of THIS classroom's dept + year."""
    return StaffProfile.objects.filter(college_user=college_user,is_active=True,staff_role="class_advisor",department_id=classroom.department_id,advisor_year=classroom.year,).exists()
 

def _build_timetable(classroom):
    """Weekly grid: rows = days, columns = periods."""
    slots = list(TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject", "teacher").order_by("day_of_week", "period_number"))
    periods = {}
    cell = {}
    for s in slots:
        print(s)
        periods.setdefault(s.period_number, (s.start_time, s.end_time))
        print(_display_name(s.teacher) if s.teacher else "")
        cell[(s.day_of_week, s.period_number)] = {"subject": s.subject_mapping.subject.short_name or s.subject_mapping.subject.name,"subject_full": s.subject_mapping.subject.name,"teacher": _display_name(s.teacher) if s.teacher else "",}
 
    period_list = [
        {"number": n, "start": periods[n][0], "end": periods[n][1]}
        for n in sorted(periods)
    ]
    rows = []
    for day_num, day_label in TimetableSlot.DAYS_OF_WEEK:
        rows.append({"day": day_label,"is_today": day_num == timezone.localdate().isoweekday(),"cells": [cell.get((day_num, p["number"])) for p in period_list],})
    return {"periods": period_list, "rows": rows, "has_slots": bool(slots)}
 
 
 
def _today_attendance(classroom, enrollments):
    
    today = timezone.localdate()
    student_ids = {e.student_id for e in enrollments}
    records = StudentAttendance.objects.filter(session__classroom=classroom, session__date=today, student_id__in=student_ids,).values_list("student_id", "status")
    present_ids, seen_ids = set(), set()
    for sid, st in records:
        seen_ids.add(sid)
        if st in ("P", "L", "OD"):
            present_ids.add(sid)
 
    present = len(present_ids)
    absent = len(seen_ids - present_ids)
    total = len(student_ids)
    periods_taken = PeriodAttendanceSession.objects.filter(classroom=classroom, date=today, is_completed=True,).count()
    return {"date": today,"present": present,"absent": absent,"not_marked": total - present - absent,"periods_taken": periods_taken,"has_data": bool(seen_ids),"percent": round(present * 100 / (present + absent)) if (present + absent) else 0,}
 
 
def _build_fee_summary(classroom, enrollments):
    """Per-student payment status for this classroom's semester. Advisor only."""
    ay_name = classroom.academic_year.name if classroom.academic_year else ""
    student_ids = [e.student_id for e in enrollments]
 
    invoices = (
        StudentFeeInvoice.objects.filter(student_id__in=student_ids, academic_year=ay_name)
        .filter(Q(semester=classroom.semester) | Q(semester__isnull=True))
        .exclude(status="cancelled")
        .annotate(paid=Coalesce(Sum("payments__amount", filter=Q(payments__status="success")),Decimal("0"),output_field=DecimalField(max_digits=12, decimal_places=2),))
    )
    by_student = defaultdict(list)
    for inv in invoices:
        by_student[inv.student_id].append(inv)
 
    today = timezone.localdate()
    counts = {"paid": 0, "partial": 0, "pending": 0, "overdue": 0, "waived": 0, "no_invoice": 0}
    rows = []
 
    for e in enrollments:
        invs = by_student.get(e.student_id, [])
        payable = [i for i in invs if i.status != "waived"]
        net = sum((i.total_amount - i.discount_amount for i in payable), Decimal("0"))
        paid = sum((i.paid for i in payable), Decimal("0"))
        balance = net - paid
 
        if not invs:
            status = "no_invoice"
        elif not payable:
            status = "waived"
        elif balance <= 0:
            status = "paid"
        elif paid > 0:
            status = "partial"
        elif any(i.due_date < today for i in payable):
            status = "overdue"
        else:
            status = "pending"
 
        counts[status] += 1
        s = e.student
        rows.append({"name": _display_name(s.college_user.user),"admission_number": s.admission_number,"roll_number": e.roll_number or s.roll_number,"net": net,"paid": paid,"balance": max(balance, Decimal("0")),"status": status,})
 
    total = len(rows)
    return {"total": total,"counts": counts,"fully_paid": counts["paid"] + counts["waived"],"rows": rows,}
 
 