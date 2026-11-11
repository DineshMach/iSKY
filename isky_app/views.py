from decimal import Decimal
from itertools import groupby
import random,io,datetime,string
from tokenize import TokenError
from types import SimpleNamespace
from typing import OrderedDict
from django.db.models import F, Q,Prefetch
from django.db.models.aggregates import Count, Sum
from django.urls import reverse
import secrets,base64,hashlib,io,qrcode
from django.db import IntegrityError, transaction, models as dj_models
from django.contrib import messages
import pandas as pd
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from datetime import datetime, time, timedelta,date
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth import get_user_model,authenticate, login as auth_login, update_session_auth_hash
from django.core.mail import send_mail
from django.shortcuts import render,get_object_or_404,redirect
from collections import defaultdict
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from .permissions import CLASS_ADVISOR, FINANCE_ADMIN, HOD, MASTER_ADMIN, OFFICE_ADMIN, STAFF, STAFF_ADMIN, IsAuthenticated,IsMasterAdmin, get_college_user
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from django.core.cache import cache
from django.contrib.auth.password_validation import validate_password

from isky_project import settings

from .serializers import AdminInvoiceDetailSerializer, AdminInvoiceListSerializer, AssignFeeStructureSerializer, BulkFeeInvoiceBatchSerializer, BulkFeeInvoiceBatchStudentSerializer, BulkInvoiceGenerateSerializer, BulkInvoiceTargetSerializer, CollegeUserCreateSerializer, CollegeUserListSerializer, EligibleStudentSerializer, FeeCategorySerializer, FeeListQuerySerializer, FeeListResponseSerializer, FeePaymentConvertToOfflineSerializer, FeePaymentDetailSerializer, FeePaymentListSerializer, FeePaymentSerializer, FeeStructureCreateSerializer,AttendanceCalendarSerializer, AttendanceSummarySerializer, BulkStaffUploadSerializer, ClassroomCreateSerializer, ClassroomListSerializer, ClassroomSerializer, CollegeSerializer, CreateCollegeAdminSerializer, CreatePlatformUserSerializer, DepartmentSerializer, DepartmentUpdateSerializer, FeeStructureCreateSerializer, FeeStructureDetailSerializer, FeeStructureItemBulkCreateSerializer, FeeStructureItemSerializer, FeeStructureItemsSummarySerializer, FeeStructureListSerializer, FeeStructureSerializer, InvoiceOfflinePaymentSerializer, InvoiceStatusOverrideSerializer, InvoiceUpdateSerializer, MappingTeacherUpdateSerializer, MarkOfflinePaymentClearedSerializer,  OfficeAdminCreateSerializer, OfficeAdminUpdateSerializer, OfflineCollectionSerializer, PaymentUpdateSerializer, PlatformUserLoginSerializer, ProfileSettingsSerializer, PromoteStudentsSerializer, RequestPasswordOTPSerializer, SaveAttendanceMatrixSerializer, StaffCreateSerializer, StaffListSerializer, StaffProfileSerializer, StaffUpdateSerializer, StudentCreateSerializer, StudentDashboardSerializer, StudentDetailSerializer, StudentFeeDetailSerializer, StudentFeeInvoiceDetailSerializer, StudentFeeInvoiceListSerializer, StudentFeeInvoiceOutputSerializer, StudentFeeInvoiceSerializer, StudentListSerializer, StudentPreviewSerializer, StudentProfileSerializer, StudentProfileUpdateSerializer, SubjectAttendanceSerializer, SubjectListSerializer, SubjectSerializer, SubjectUpdateSerializer, TimetableGridSaveSerializer, TimetableSlotCreateSerializer, TimetableSlotListSerializer, VerifyPasswordOTPSerializer, invoice_amounts
from .models import BLOOD_GROUP_CHOICES, AcademicYear, BulkFeeInvoiceBatch, BulkFeeInvoiceBatchStudent, Classroom, College, CollegeUser, Department, DepartmentSubjectMapping, FeeCategory, FeeConcession, FeePayment, FeeStructure, FeeStructureItem, LoginAttempt, LoginSecurity, PaymentHistory, PeriodAttendanceSession, SettlementBatch, StaffProfile, StudentAttendance, StudentEnrollment, StudentFeeInvoice, StudentFeeInvoiceItem, StudentProfile, Subject, TimetableSlot, TrustedDevice, OTPVerification, DeviceIPHistory, User
from .helper import OTP_TTL, _build_fee_summary, _build_timetable, _can_manage_classroom, _compute_payment_status, _display_name, _get_classroom_and_year, _get_college_user, _get_object_or_404_uuid, _get_scoped_classroom, _is_class_advisor, _otp_key, _resolve_academic_year, _sort_students, _today_attendance, build_profile, can_edit_timetable_for, creatable_departments, editable_attendance_slot_ids, editable_timetable_classrooms, enroll_student, find_classroom, get_classroom_access, get_client_ip, get_device_info, get_membership, get_promotion_access, get_schedule_access, hash_device_token, mask_email, scope_classrooms, scope_promotion_students, scope_schedule_classrooms, valid_uuid, visible_departments
from .permissions import IsMasterOrOfficeAdmin,_role_matches
from .mail import send_password_change_otp_email,send_login_verification_otp_email,_send_otp_email, _send_welcome_email, send_password_reset_otp_email, staff_create_account, student_create_account
from django.utils.crypto import constant_time_compare, get_random_string
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
import calendar as cal
from .services import PaymentAttemptExpired,InvalidPaymentAttempt, InvoiceAlreadyExists, NothingToPayError, generate_invoice_for_student, generate_payment_link, initiate_online_payment, process_mock_gateway_callback


OTP_VALIDITY_MINUTES = 10
OTP_MAX_ATTEMPTS = 5


def custom_404_view(request, exception):
    return render(request, "404.html", status=404)

def custom_500_view(request):
    return render(request, "500.html", status=500)

#=============================================================================================================================================
# NOTE :- PLATFORM ADMIN -----------------
#=============================================================================================================================================


# -------------------------------------------------------------------
# 1. Create Platform Admin API
# -------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([AllowAny])  # Change to [IsPlatformAdmin] to restrict creation to existing platform admins
def create_platform_user_api_view(request):
    """Creates a user with user_type='platform_admin'."""
    print(request.data)
    serializer = CreatePlatformUserSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response({"success": True,"message": "Platform Admin created successfully.","data": {"id": str(user.id),"email": user.email,"user_type": user.user_type,"status": user.status,}},status=status.HTTP_201_CREATED)
    return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)



# -------------------------------------------------------------------
# 2. Platform Admin Login API
# -------------------------------------------------------------------
@api_view(["GET","POST"])
@permission_classes([AllowAny])
def platform_user_login_api_view(request):

    if request.method == "GET":
        return render(request, "PlatformAdmin/login.html", {"form": {"non_field_errors": ["Invalid Employee ID or password."]}})
    
    """Authenticates Platform Admin and returns JWT tokens along with 2FA check logic."""
    users = User.objects.all()
    print(users)
    serializer = PlatformUserLoginSerializer(data=request.data)
    
    if serializer.is_valid():
        user = serializer.validated_data["user"]

        # 2FA Check Step
        if user.is_2fa_enabled:
            # Generate a temporary login session token if 2FA is active
            import secrets
            temp_token = secrets.token_urlsafe(32)
            request.session["pending_login"] = {"user_id": str(user.id),"temporary_token": temp_token}
            return Response({"success": True,"requires_2fa": True,"temporary_token": temp_token,"message": "2FA required. Enter TOTP code to complete login."},status=status.HTTP_200_OK)

        # Standard direct login flow (Issue JWT Tokens)
        user.last_login_at = timezone.now()
        user.last_login_ip = request.META.get("REMOTE_ADDR")
        user.save(update_fields=["last_login_at", "last_login_ip"])
        refresh = RefreshToken.for_user(user)
        request.session["access_token"] = str(refresh.access_token)
        request.session["refresh_token"] = str(refresh)
        request.session["user_id"] = str(user.id)
        return Response(
            {
                "success": True,
                "requires_2fa": False,
                "message": "Login successful.",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "user_type": user.user_type,
                }
            },
            status=status.HTTP_200_OK
        )

    return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class IsPlatformAdmin(BasePermission):
    """Only active platform admins may use the platform API."""
    message = "Platform admin access required."
 
    def has_permission(self, request, view):
        u = request.user
        return bool(
            u and u.is_authenticated
            and u.user_type == "platform_admin"
            and u.status == "active"
        )
 
 
# ---------------------------------------------------------------------------
# Pages
# These are NOT login-protected on purpose: the browser navigates to them
# without an Authorization header (the JWT lives in localStorage). The page JS
# redirects to login when there is no token, and every API call below enforces
# IsPlatformAdmin, so no data is exposed.
# ---------------------------------------------------------------------------
@api_view(["GET","POST"])
@permission_classes([AllowAny])
def platform_dashboard_page(request):
    return render(request, "PlatformAdmin/dashboard.html")

@api_view(["GET","POST"])
@permission_classes([AllowAny])
def platform_colleges_page(request):
    return render(request, "PlatformAdmin/colleges.html")
 
@api_view(["GET","POST"])
@permission_classes([AllowAny])
def platform_college_users_page(request):
    return render(request, "PlatformAdmin/college_users.html")
 
# ---------------------------------------------------------------------------
# API: colleges    GET /api/platform/colleges/    POST /api/platform/colleges/
# ---------------------------------------------------------------------------
 
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsPlatformAdmin])
def platform_colleges(request):
    if request.method == "GET":
        colleges = College.objects.all().order_by("name")
        return Response(CollegeSerializer(colleges, many=True).data)
 
    serializer = CollegeSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 
 
# ---------------------------------------------------------------------------
# API: college users    GET/POST /api/platform/college-users/
#   GET filters (all optional): ?college=<uuid>  ?role=<role>  ?q=<text>
# ---------------------------------------------------------------------------
 
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsPlatformAdmin])
def platform_college_users(request):
    if request.method == "GET":
        memberships = (
            CollegeUser.objects.select_related("user", "college")
            .order_by("-created_at")
        )
        college_id = request.query_params.get("college")
        role = request.query_params.get("role")
        q = request.query_params.get("q", "").strip()
 
        if college_id:
            memberships = memberships.filter(college_id=college_id)
        if role:
            memberships = memberships.filter(role=role)
        if q:
            memberships = memberships.filter(
                Q(user__email__icontains=q)
                | Q(user__first_name__icontains=q)
                | Q(user__last_name__icontains=q)
                | Q(college__name__icontains=q)
            )
        return Response(CollegeUserListSerializer(memberships, many=True).data)
 
    serializer = CollegeUserCreateSerializer(data=request.data)
    if serializer.is_valid():
        membership = serializer.save()
        return Response(
            CollegeUserListSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



#=============================================================================================================================================
# NOTE :- COLLEGE ADMIN -----------------
#=============================================================================================================================================

def home(request):
    return render(request, "home.html")

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def authentication_error_view(request):
    return render(request,"errors/authentication_error.html")

def admin_login(request):
    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        password = request.POST.get("password")
        return render(request, "admin_login.html", {"form": {"non_field_errors": ["Invalid Employee ID or password."]}})
    return render(request, "Admin/admin_login.html")

def _hash_otp(code):
    return hashlib.sha256(code.encode()).hexdigest()


def _issue_otp(user, purpose="password_reset", channel="email"):
    # invalidate any previous unused OTPs of this purpose for this user
    OTPVerification.objects.filter(user=user, purpose=purpose, is_used=False, verified_at__isnull=True).delete()

    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    otp = OTPVerification.objects.create(user=user,purpose=purpose,channel=channel,otp_hash=_hash_otp(code),expires_at=timezone.now() + timedelta(minutes=OTP_VALID_MINUTES),)
    return otp, code


def _check_otp(user, code, purpose="password_reset"):
    otp = OTPVerification.objects.filter(user=user, purpose=purpose, is_used=False).order_by("-created_at").first()

    if not otp:
        return False, "No active code found. Please request a new one."
    if otp.is_expired():
        return False, "This code has expired. Please request a new one."
    if otp.attempts >= otp.max_attempts:
        return False, "Too many attempts. Please request a new code."

    otp.attempts += 1

    if otp.otp_hash == _hash_otp(code):
        otp.is_used = True
        otp.verified_at = timezone.now()
        otp.save(update_fields=["attempts", "is_used", "verified_at"])
        return True, None

    otp.save(update_fields=["attempts"])
    remaining = otp.max_attempts - otp.attempts
    if remaining <= 0:
        return False, "Too many attempts. Please request a new code."
    return False, f"Invalid code. {remaining} attempt(s) left."


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@transaction.atomic
def staff_login(request):
    if request.method == "GET":
        return render(request, "Admin/staff_login.html")

    role = request.POST.get("role")        # 'hod' | 'faculty_advisor' | 'staff'
    staff_id = request.POST.get("staff_id")
    password = request.POST.get("password")

    if not staff_id or not password:
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["Staff ID and password are required."]}})

    ip_address = get_client_ip(request)
    device_info = get_device_info(request)

    # --------------------------------------------------
    # 1. Find User & Verify Active Membership
    # --------------------------------------------------
    try:
        user = User.objects.get(email=staff_id)
    except User.DoesNotExist:
        LoginAttempt.objects.create(user=None, ip_address=ip_address, user_agent=device_info["user_agent"], result="failed_password")
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["Invalid Staff ID or password."]}})
    membership = CollegeUser.objects.filter(user=user, role="staff_admin", status="active").select_related("user").first()

    if not membership or user.status != "active" or not user.is_active:
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="blocked")
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["Unable to login or account inactive."]}})

    # --------------------------------------------------
    # 2. Check Cooldown
    # --------------------------------------------------
    security, _ = LoginSecurity.objects.get_or_create(user=user)
    if security.is_in_cooldown():
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="cooldown")
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["Too many failed attempts. Please try again later."]}})

    # --------------------------------------------------
    # 3. Authenticate Password
    # --------------------------------------------------
    authenticated_user = authenticate(request=request, username=user.username, password=password)
    if authenticated_user is None:
        security.failed_attempts += 1
        if security.failed_attempts >= 5:
            security.status = "cooldown"
            security.cooldown_until = timezone.now() + timedelta(minutes=15)
        security.save()
        
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="failed_password")
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["Invalid Staff ID or password."]}})
    
    
    # Reset security counters on password success
    security.failed_attempts = 0
    security.status = "active"
    security.cooldown_until = None
    security.save()
    
    staff_profile = getattr(membership, "staff_profile", None)
    actual_role = staff_profile.staff_role if staff_profile else None

    if not _role_matches(role, actual_role):
        LoginAttempt.objects.create(user=user, ip_address=ip_address,user_agent=device_info["user_agent"], result="blocked",)
        return render(request, "Admin/staff_login.html", {"form": {"non_field_errors": ["These credentials don't belong to the selected role. Please choose the correct role and try again."]}})


    # --------------------------------------------------
    # 4. Check First-Time Login (Temporary Random Password Setup)
    # --------------------------------------------------
    if not user.password_updated:
        request.session["pending_setup_user_id"] = str(user.id)
        request.session["setup_role"] = role
        request.session["otp_verified"] = False
        _otp, code = _issue_otp(user, purpose="password_reset", channel="email")
        _send_otp_email(user, code)
        return redirect("email-auth-verification")

    # --------------------------------------------------
    # 5. Check Device Cookie (Trusted Device Check)
    # --------------------------------------------------
    raw_device_token = request.COOKIES.get("device_token")
    print("device token ============= ")
    
    print(request.COOKIES.get("device_token"))
    print(raw_device_token)
    trusted_device = None

    if raw_device_token:
        token_hash = hash_device_token(raw_device_token)
        print("device token =============  checking")
        print(token_hash)
        trusted_device = TrustedDevice.objects.filter(user=user, device_token_hash=token_hash, is_active=True, is_trusted=True).first()

        if trusted_device and trusted_device.expires_at and trusted_device.expires_at < timezone.now():
            print("not trusted")
            trusted_device.is_trusted = False
            trusted_device.save(update_fields=["is_trusted"])
            trusted_device = None

    # If already a trusted device, skip OTP/2FA and complete login
    if trusted_device:
        auth_login(request, user)
        _complete_login(request=request, user=user, device=trusted_device, ip_address=ip_address, device_info=device_info, new_device=False)
        return _redirect_by_role(role)

    # --------------------------------------------------
    # 6. Check 2FA (Authenticator App / TOTP)
    # --------------------------------------------------
    temporary_token = secrets.token_urlsafe(32)
    if getattr(user, "is_2fa_enabled", False):
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="2fa_required")
        request.session["pending_login"] = {"user_id": str(user.id),"temporary_token": temporary_token,"auth_type": "totp","role": role}
        return redirect("verify_2fa")  # Redirect to your TOTP verification view
    # --------------------------------------------------
    # 7. Untrusted / New Device Verification (Email OTP)
    # --------------------------------------------------
    LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="new_device")
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    OTPVerification.objects.filter(user=user, purpose="new_device", is_used=False).update(is_used=True)
    verification = OTPVerification.objects.create(user=user,purpose="new_device",channel="email",otp_hash=otp_hash,expires_at=timezone.now() + timedelta(minutes=5))
    request.session["pending_login"] = {"user_id": str(user.id),"verification_id": str(verification.id),"temporary_token": temporary_token,"role": role}
    send_login_verification_otp_email(user,otp)
    return redirect("email-auth-verification")  # Redirect to email OTP verification view


def _redirect_by_role(role):
    
    if role == "hod":
        return redirect("master-admin-dashboard")
    if role == "faculty_advisor":
        return redirect("master-admin-dashboard")
    if role == "staff":
            return redirect("master-admin-dashboard")
    return redirect("student-dashboard")

def _resolve_role_and_template(request, user):
    role = (request.session.get("setup_role") or request.session.get("pending_login", {}).get("role"))
    if not role:
        membership = CollegeUser.objects.filter(user=user).first()
        role = membership.role if membership else "staff"
    
    template = "Student/student_email_auth_verify.html" if role == "student" else "Admin/email_auth_verify.html"
    return role, template


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def verify_otp_and_setup(request):
    # --------------------------------------------------
    # Check Session State
    # --------------------------------------------------
    pending_setup_user_id = request.session.get("pending_setup_user_id")
    pending_login = request.session.get("pending_login", {})
    user_id = pending_setup_user_id or pending_login.get("user_id")
    if not user_id:
        return redirect("staff_login")
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect("staff_login")
    print(" is this the problem?")
    role, template_name = _resolve_role_and_template(request, user)
    print(role,template_name)
    print(" Nope")
    context = {"email": user.email,"otp_verified": request.session.get("otp_verified", False),"error": None,"resent": False,}
    if request.method == "POST":
        action = request.POST.get("action")
        # --------------------------------------------------
        # Action A: Verify OTP
        # --------------------------------------------------
        if action == "verify_otp":
            otp_digits = [request.POST.get(f"otp_{i}", "") for i in range(1, 7)]
            submitted_otp = "".join(otp_digits).strip()
            if len(submitted_otp) != 6 or not submitted_otp.isdigit():
                context["error"] = "Please enter a valid 6-digit code."
                return render(request, template_name, context)
            otp_hash = hashlib.sha256(submitted_otp.encode("utf-8")).hexdigest()
            # Determine Purpose ('password_reset' or 'new_device')
            purpose = "password_reset" if pending_setup_user_id else "new_device"
            verification = OTPVerification.objects.filter(user=user,purpose=purpose,otp_hash=otp_hash,is_used=False,expires_at__gt=timezone.now()).first()
            if not verification:
                context["error"] = "Invalid or expired verification code."
                return render(request, template_name, context)

            # Mark OTP as used
            verification.is_used = True
            verification.save(update_fields=["is_used"])

            # FLOW 1: First-time Password Setup -> Render password reset form
            if pending_setup_user_id:
                request.session["otp_verified"] = True
                context["otp_verified"] = True
                return render(request, template_name, context)
            # FLOW 2: New Device Login -> Register Device & Complete Login
            if pending_login:
                role = pending_login.get("role", "staff")
                # Device Registration
                raw_device_token = secrets.token_urlsafe(32)
                token_hash = hash_device_token(raw_device_token)
                TrustedDevice.objects.create(user=user,device_token_hash=token_hash,device_name=request.META.get("HTTP_USER_AGENT", "Unknown Device")[:100],is_active=True,is_trusted=True,expires_at=timezone.now() + timedelta(days=30))
                # Authenticate & Clean session
                auth_login(request, user)
                # del request.session["pending_login"]
                
                print("pending login")
                response = _redirect_by_role(role)
                response.set_cookie(key="device_token",value=raw_device_token,max_age=30 * 24 * 60 * 60,path="/", httponly=True, secure=not settings.DEBUG,samesite="Lax",)
                print(request.COOKIES)
                refresh = RefreshToken.for_user(user)
                print(refresh)
                request.session["access_token"] = str(refresh.access_token)
                request.session["refresh_token"] = str(refresh)
                request.session["user_id"] = str(user.id)
                return response

        # --------------------------------------------------
        # Action B: Resend OTP
        # --------------------------------------------------
        elif action == "resend_otp":
            purpose = "password_reset" if pending_setup_user_id else "new_device"
            
            # Issue and email new code
            _otp, code = _issue_otp(user, purpose=purpose, channel="email")
            _send_otp_email(user, code)

            context["resent"] = True
            return render(request, template_name, context)

        # --------------------------------------------------
        # Action C: Set New Password (First-Time Login Setup)
        # --------------------------------------------------
        elif action == "reset_password":
            if not request.session.get("otp_verified"):
                context["error"] = "Please verify your email code first."
                return render(request, template_name, context)

            password1 = request.POST.get("password1")
            password2 = request.POST.get("password2")

            if password1 != password2:
                context["otp_verified"] = True
                context["error"] = "Passwords do not match."
                return render(request, template_name, context)

            if len(password1) < 8:
                context["otp_verified"] = True
                context["error"] = "Password must be at least 8 characters."
                return render(request, template_name, context)

            # Update password state
            user.password = make_password(password1)
            user.password_updated = True
            user.save(update_fields=["password", "password_updated"])

            # Clean session & Complete Login
            role = request.session.get("setup_role", "staff")
            if "pending_setup_user_id" in request.session:
                del request.session["pending_setup_user_id"]
            if "otp_verified" in request.session:
                del request.session["otp_verified"]
                
            _send_welcome_email(user)
            auth_login(request, user)
            refresh = RefreshToken.for_user(user)
            print(refresh)
            request.session["access_token"] = str(refresh.access_token)
            request.session["refresh_token"] = str(refresh)
            request.session["user_id"] = str(user.id)
            print("complete")
            # return
            return _redirect_by_role(role)
    print(context)
    return render(request, template_name, context)

@api_view(["GET","POST"])
@permission_classes([AllowAny])
def staff_update_password(request):
    user_id = request.session.get("pending_setup_user_id")
    if not user_id:
        return redirect("staff_login")
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        request.session.flush()
        return redirect("staff_login")
    otp_verified = request.session.get("otp_verified", False)
    error = None
    resent = False
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "resend_otp":
            _otp, code = _issue_otp(user, purpose="password_reset", channel="email")
            _send_otp_email(user, code)
            resent = True

        elif action == "verify_otp":
            code = "".join(request.POST.get(f"otp_{i}", "") for i in range(1, 7))
            success, err = _check_otp(user, code, purpose="password_reset")
            if success:
                request.session["otp_verified"] = True
                otp_verified = True
            else:
                error = err

        elif action == "reset_password" and otp_verified:
            pwd1 = request.POST.get("password1", "")
            pwd2 = request.POST.get("password2", "")

            if pwd1 != pwd2:
                error = "Passwords do not match."
            elif len(pwd1) < 8:
                error = "Password must be at least 8 characters."
            else:
                user.set_password(pwd1)
                user.password_updated = True
                user.save(update_fields=["password", "password_updated"])
                role = request.session.pop("setup_role", None)
                request.session.pop("pending_setup_user_id", None)
                request.session.pop("otp_verified", None)
                _send_welcome_email(user)
                auth_login(request, user)

                if role == "hod":
                    return redirect("master-admin-dashboard")
                if role == "faculty_advisor":
                    return redirect("master-admin-dashboard")
                return redirect("master-admin-dashboard")

    return render(request, "Admin/staff_update_password.html", {"email": user.email,"otp_verified": otp_verified,"error": error,"resent": resent,})
    
    
def _complete_login(request, user, device, ip_address, device_info, new_device=False):
    """Helper function to execute standard successful login operations."""
    # Update device
    device.last_ip = ip_address
    device.last_seen_at = timezone.now()
    device.save(update_fields=["last_ip", "last_seen_at"])
    # IP history
    ip_history, created = DeviceIPHistory.objects.get_or_create(device=device,ip_address=ip_address)
    if not created:
        ip_history.login_count += 1
        ip_history.save(update_fields=["login_count", "last_seen_at"])
    # User login information
    user.last_login_ip = ip_address
    user.last_login_device = device
    user.last_login_at = timezone.now()
    user.save(update_fields=["last_login_ip", "last_login_device", "last_login_at"])
    # Login security
    security = user.login_security
    security.last_ip = ip_address
    security.last_device = device
    security.last_login = timezone.now()
    security.save(update_fields=["last_ip", "last_device", "last_login"])
    # Login history
    LoginAttempt.objects.create(user=user,ip_address=ip_address,device=device,user_agent=device_info["user_agent"],result="success")
    # JWT
    refresh = RefreshToken.for_user(user)
    response = Response(
        {
            "success": True,
            "message": "Login successful.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": str(user.id),
                "email": user.email,
                "user_type": user.user_type,
            }
        },
        status=status.HTTP_200_OK
    )

    # Set trusted device cookie for new devices
    if new_device:
        raw_token = secrets.token_urlsafe(64)
        response.set_cookie(key="device_token",value=raw_token,max_age=60 * 60 * 24 * 30,secure=True,httponly=True,samesite="Lax")

    # Login notification
    refresh = RefreshToken.for_user(user)
    # --------------------------------------------------
    # Send email
    # --------------------------------------------------
    print(refresh)
    request.session["access_token"] = str(refresh.access_token)
    request.session["refresh_token"] = str(refresh)
    request.session["user_id"] = str(user.id)
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def setup_2fa_view(request):
    user = request.user
    # Ensure secret exists
    user.generate_totp_secret()
    totp_uri = user.get_totp_uri()
    # Generate QR Code in memory
    qr = qrcode.make(totp_uri)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
    return Response({"success": True,"secret": user.totp_secret,"qr_code": f"data:image/png;base64,{qr_base64}"}, status=status.HTTP_200_OK)  # Used for manual entry in authenticator

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def enable_2fa_view(request):
    user = request.user
    code = request.data.get("code")
    if not code:
        return Response({"success": False, "message": "Verification code is required."},status=status.HTTP_400_BAD_REQUEST)
    if user.verify_totp(code):
        user.is_2fa_enabled = True
        user.save(update_fields=["is_2fa_enabled"])
        return Response({"success": True, "message": "Two-Factor Authentication enabled successfully."},status=status.HTTP_200_OK)
    return Response({"success": False, "message": "Invalid verification code."},status=status.HTTP_400_BAD_REQUEST)



@api_view(["GET","POST"])
@permission_classes([AllowAny])
@transaction.atomic
def login_api_view(request):
    if request.method == "GET":
        return render(request, "Admin/admin_login.html")
    user_id = request.data.get("user_id")
    password = request.data.get("password")

    if not user_id or not password:
        messages.error(request,"User ID and password are required.")
        return redirect('college-admin-login')
        # return Response({"success": False,"message": "User ID and password are required."},status=status.HTTP_400_BAD_REQUEST)

    ip_address = get_client_ip(request)
    device_info = get_device_info(request)

    # --------------------------------------------------
    # Find user
    # --------------------------------------------------
    try:
        user = User.objects.get(username=user_id)
        is_admin = CollegeUser.objects.get(user=user.id).role
        if is_admin not in ("master_admin", "office_admin"):
            messages.error(request,"You don't have permission to access this page.")
            return redirect('college-admin-login')
    except User.DoesNotExist:
        print("does not exist")
        LoginAttempt.objects.create(user=None,ip_address=ip_address,user_agent=device_info["user_agent"],result="failed_password")
        messages.error(request,"Invalid User ID or password.")
        return redirect('college-admin-login')
        return Response({"success": False,"message": "Invalid User ID or password."},status=status.HTTP_401_UNAUTHORIZED)
    
        

    # --------------------------------------------------
    # Check user status
    # --------------------------------------------------
    if user.status != "active" or not user.is_active:
        LoginAttempt.objects.create(user=user,ip_address=ip_address,user_agent=device_info["user_agent"],result="blocked")
        messages.error(request,"Unable to login.")
        return redirect('college-admin-login')
        return Response({"success": False,"message": "Unable to login."},status=status.HTTP_403_FORBIDDEN)

    # --------------------------------------------------
    # Get LoginSecurity
    # --------------------------------------------------
    security, _ = LoginSecurity.objects.get_or_create(user=user)

    # --------------------------------------------------
    # Check cooldown
    # --------------------------------------------------
    if security.is_in_cooldown():
        LoginAttempt.objects.create(user=user,ip_address=ip_address,user_agent=device_info["user_agent"],result="cooldown")
        messages.error(request,f"Too many failed attempts.Try after {security.cooldown_until}s ")
        return redirect('college-admin-login')
        return Response({"success": False,"message": "Too many failed attempts.","cooldown_until": security.cooldown_until},status=status.HTTP_429_TOO_MANY_REQUESTS)

    # --------------------------------------------------
    # Authenticate password
    # --------------------------------------------------
    authenticated_user = authenticate(request=request,username=user.username,password=password)
    print(authenticated_user)
    if authenticated_user is None:
        security.failed_attempts += 1
        if security.failed_attempts >= 5:
            security.status = "cooldown"
            security.cooldown_until = timezone.now() + timedelta(minutes=15)
        security.save()
        LoginAttempt.objects.create(user=user,ip_address=ip_address,user_agent=device_info["user_agent"],result="failed_password")
        messages.error(request,"Invalid User ID or password.")
        return redirect('college-admin-login')
        return Response({"success": False,"message": "Invalid User ID or password."},status=status.HTTP_401_UNAUTHORIZED)

    # --------------------------------------------------
    # Password correct
    # --------------------------------------------------
    security.failed_attempts = 0
    security.status = "active"
    security.cooldown_until = None
    security.save()

    # --------------------------------------------------
    # Check device cookie
    # --------------------------------------------------
    raw_device_token = request.COOKIES.get("device_token")
    trusted_device = None

    if raw_device_token:
        token_hash = hash_device_token(raw_device_token)
        trusted_device = TrustedDevice.objects.filter(user=user,device_token_hash=token_hash,is_active=True,is_trusted=True,).first()
        if trusted_device:
            if trusted_device.expires_at and trusted_device.expires_at < timezone.now():
                trusted_device.is_trusted = False
                trusted_device.save(update_fields=["is_trusted"])
                trusted_device = None

    # --------------------------------------------------
    # Existing trusted device
    # --------------------------------------------------
    if trusted_device:
        return _complete_login(request=request,user=user,device=trusted_device,ip_address=ip_address,device_info=device_info,new_device=False)

    # --------------------------------------------------
    # Branching for 2FA vs Email OTP (Untrusted / New Device)
    # --------------------------------------------------
    temporary_token = secrets.token_urlsafe(32)

    # Option A: User HAS 2FA enabled (Authenticator app / TOTP)
    if getattr(user, "is_2fa_enabled", False):
        LoginAttempt.objects.create(user=user,ip_address=ip_address,user_agent=device_info["user_agent"],result="2fa_required")
        request.session["pending_login"] = {"user_id": str(user.id),"temporary_token": temporary_token,"auth_type": "totp"}
        return Response({"success": True,"requires_2fa": True,"2fa_type": "totp","temporary_token": temporary_token,"message": "Please enter the code from your authenticator app.",},status=status.HTTP_200_OK)  # Signal frontend to show authenticator app prompt
    
    # --------------------------------------------------
    # New device
    # --------------------------------------------------
    LoginAttempt.objects.create(user=user,ip_address=ip_address,user_agent=device_info["user_agent"],result="new_device")

    # Generate OTP
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    OTPVerification.objects.filter(user=user,purpose="new_device",is_used=False).update(is_used=True)
    verification = OTPVerification.objects.create(user=user,purpose="new_device",channel="email",otp_hash=otp_hash,expires_at=timezone.now() + timedelta(minutes=5),)
    temporary_token = secrets.token_urlsafe(32)
    refresh = RefreshToken.for_user(user)
    request.session["pending_login"] = {"verification_id": str(verification.id),"temporary_token": temporary_token,}

    # --------------------------------------------------
    # Send email
    # --------------------------------------------------
    send_login_verification_otp_email(user,otp)
    
    request.session["access_token"] = str(refresh.access_token)
    request.session["refresh_token"] = str(refresh)
    request.session["user_id"] = str(user.id)
    
    return redirect('master-admin-dashboard')
    return Response({"success": True,"requires_2fa": True,"requires_new_device_verification": True,"access": str(refresh.access_token),"temporary_token": temporary_token,"message": "A verification code has been sent to your registered email.",},status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([AllowAny])
def logout_view(request):
    refresh_token = (request.data.get("refresh") or request.session.get("refresh_token"))

    if refresh_token:
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            pass
        except AttributeError:
            pass
    request.session.flush()
    response = Response({"success": True,"message": "Logged out successfully."},status=status.HTTP_200_OK)
    response.delete_cookie("device_token",path="/",samesite="Lax")
    return render(request, "Admin/admin_login.html")

@api_view(["POST"])
@permission_classes([AllowAny])
def verify_totp_login_view(request):
    temporary_token = request.data.get("temporary_token")
    code = request.data.get("code")
    pending_login = request.session.get("pending_login")
    if not pending_login or pending_login.get("temporary_token") != temporary_token:
        return Response({"success": False, "message": "Invalid or expired session. Please login again."},status=status.HTTP_401_UNAUTHORIZED)
    try:
        user = User.objects.get(id=pending_login["user_id"])
    except User.DoesNotExist:
        return Response({"success": False, "message": "User not found."},status=status.HTTP_404_NOT_FOUND)
    if user.verify_totp(code):
        # Clear session key
        del request.session["pending_login"]
        # Return success using helper (or issue DRF/JWT tokens)
        return Response({"success": True,"message": "2FA Verification successful."}, status=status.HTTP_200_OK)# Call your complete_login logic here
    return Response({"success": False, "message": "Invalid 2FA code."},status=status.HTTP_400_BAD_REQUEST)


OTP_VALID_MINUTES = 10
OTP_LENGTH = 6


def _hash_otp(code):
    return hashlib.sha256(code.encode()).hexdigest()


def _issue_otp(user, purpose="password_reset", channel="email"):
    # invalidate any previous unused OTPs of this purpose for this user
    OTPVerification.objects.filter(user=user, purpose=purpose, is_used=False, verified_at__isnull=True).delete()

    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    otp = OTPVerification.objects.create(user=user,purpose=purpose,channel=channel,otp_hash=_hash_otp(code),expires_at=timezone.now() + timedelta(minutes=OTP_VALID_MINUTES),)
    return otp, code


def _check_otp(user, code, purpose="password_reset"):
    """Returns (success: bool, error: str|None)."""
    otp = OTPVerification.objects.filter(user=user, purpose=purpose, is_used=False).order_by("-created_at").first()

    if not otp:
        return False, "No active code found. Please request a new one."
    if otp.is_expired():
        return False, "This code has expired. Please request a new one."
    if otp.attempts >= otp.max_attempts:
        return False, "Too many attempts. Please request a new code."

    otp.attempts += 1

    if otp.otp_hash == _hash_otp(code):
        otp.is_used = True
        otp.verified_at = timezone.now()
        otp.save(update_fields=["attempts", "is_used", "verified_at"])
        return True, None

    otp.save(update_fields=["attempts"])
    remaining = otp.max_attempts - otp.attempts
    if remaining <= 0:
        return False, "Too many attempts. Please request a new code."
    return False, f"Invalid code. {remaining} attempt(s) left."

RESET_SESSION_KEY = "pw_reset"
RESET_RESEND_SECONDS = 60
RESET_VERIFIED_MINUTES = 10

def _mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"


def _send_reset_otp(user, code):
    print(code)
    send_password_reset_otp_email(user_name=user.get_full_name() or user.email,user_email=user.email,otp=code,expires_in_minutes=OTP_VALIDITY_MINUTES,)
    



@api_view(["POST","GET"])
@permission_classes([AllowAny])
def forgot_password_view(request):
    """Step 1: ask for Employee ID and email the OTP."""
    if request.method == "GET":
        return render(request, "Admin/forgot_password.html")

    user_id = (request.POST.get("user_id") or "").strip()
    if not user_id:
        return render(request, "Admin/forgot_password.html", {"error": "Please enter your Employee ID."})

    user = User.objects.filter(username=user_id).first()
    state = {"user_id": None, "email_hint": "your registered email", "verified_at": None}

    if user and user.is_active and user.status == "active" and user.email:
        try:
            _, code = _issue_otp(user)
            send_password_reset_otp_email(user_name=user.get_full_name() or user.email,user_email=user.email,otp=code,expires_in_minutes=OTP_VALIDITY_MINUTES,)
           
        except Exception:
            return render(request, "Admin/forgot_password.html",{"error": "Could not send the code. Please try again.","code":code})
        state.update(user_id=str(user.id), email_hint=_mask_email(user.email))

    # Same response whether or not the ID exists, so IDs can't be guessed
    request.session[RESET_SESSION_KEY] = state
    return redirect("reset-password")



@api_view(["POST","GET"])
@permission_classes([AllowAny])
def reset_password_view(request):
    import time
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    """Step 2: verify OTP, then step 3: set new password and log in."""
    state = request.session.get(RESET_SESSION_KEY)
    if not state:
        return redirect("forgot-password")

    user = User.objects.filter(id=state["user_id"]).first() if state.get("user_id") else None

    # verified state expires after a few minutes
    verified_at = state.get("verified_at")
    if verified_at and time.time() - verified_at > RESET_VERIFIED_MINUTES * 60:
        state["verified_at"] = None
        request.session[RESET_SESSION_KEY] = state
        verified_at = None

    ctx = {"email": state["email_hint"], "otp_verified": bool(verified_at)}

    if request.method == "GET":
        return render(request, "Admin/email_auth_verify.html", ctx)

    action = request.POST.get("action")

    # ---------------- verify OTP ----------------
    if action == "verify_otp":
        code = "".join((request.POST.get(f"otp_{i}") or "").strip() for i in range(1, OTP_LENGTH + 1))
        if not user or len(code) != OTP_LENGTH or not code.isdigit():
            ctx["error"] = "Invalid or expired code."
        else:
            ok, err = _check_otp(user, code)
            if ok:
                state["verified_at"] = time.time()
                request.session[RESET_SESSION_KEY] = state
                ctx["otp_verified"] = True
            else:
                ctx["error"] = err

    # ---------------- resend OTP ----------------
    elif action == "resend_otp":
        if user:
            last = (OTPVerification.objects.filter(user=user, purpose="password_reset").order_by("-created_at").first())
            if last and (timezone.now() - last.created_at).total_seconds() < RESET_RESEND_SECONDS:
                ctx["error"] = "Please wait a minute before requesting another code."
                return render(request, "Admin/email_auth_verify.html", ctx)
            try:
                _, code = _issue_otp(user)
                send_password_reset_otp_email(user_name=user.get_full_name() or user.email,user_email=user.email,otp=code,expires_in_minutes=OTP_VALIDITY_MINUTES,)
            except Exception:
                ctx["error"] = "Could not send the code. Please try again."
                return render(request, "Admin/email_auth_verify.html", ctx)
        ctx["resent"] = True

    # ---------------- set new password ----------------
    elif action == "reset_password":
        if not user or not verified_at:
            ctx["otp_verified"] = False
            ctx["error"] = "Please verify the code first."
            return render(request, "Admin/email_auth_verify.html", ctx)

        p1 = request.POST.get("password1", "")
        p2 = request.POST.get("password2", "")
        if p1 != p2:
            ctx["error"] = "Passwords do not match."
            return render(request, "Admin/email_auth_verify.html", ctx)
        try:
            validate_password(p1, user)
        except ValidationError as e:
            ctx["error"] = " ".join(e.messages)
            return render(request, "Admin/email_auth_verify.html", ctx)

        user.set_password(p1)
        user.save(update_fields=["password"])

        # clear any lockout from earlier failed logins
        security, _ = LoginSecurity.objects.get_or_create(user=user)
        security.failed_attempts = 0
        security.status = "active"
        security.cooldown_until = None
        security.save()

        # log the user in, then move to the dashboard
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        refresh = RefreshToken.for_user(user)
        request.session["access_token"] = str(refresh.access_token)
        request.session["refresh_token"] = str(refresh)
        request.session["user_id"] = str(user.id)
        request.session.pop(RESET_SESSION_KEY, None)

        messages.success(request, "Password updated successfully. Welcome back!")
        return redirect("master-admin-dashboard")

    return render(request, "Admin/email_auth_verify.html", ctx)


# -------------------------------------------------------------------
# 1. College APIs
# -------------------------------------------------------------------
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def college_list_create_api_view(request):

    if request.method == "GET":
        colleges = College.objects.all().order_by("-created_at")
        serializer = CollegeSerializer(colleges, many=True)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    elif request.method == "POST":
        serializer = CollegeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "College created successfully.", "data": serializer.data},
                status=status.HTTP_201_CREATED
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def college_detail_api_view(request, pk):
    college = get_object_or_404(College, pk=pk)

    if request.method == "GET":
        serializer = CollegeSerializer(college)
        return Response({"success": True, "data": serializer.data}, status=status.HTTP_200_OK)

    elif request.method in ["PUT", "PATCH"]:
        partial = request.method == "PATCH"
        serializer = CollegeSerializer(college, data=request.data, partial=partial)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "College updated successfully.", "data": serializer.data},
                status=status.HTTP_200_OK
            )
        return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == "DELETE":
        college.is_active = False
        college.status = "inactive"
        college.save()
        return Response({"success": True, "message": "College deactivated successfully."}, status=status.HTTP_200_OK)


# -------------------------------------------------------------------
# 2. College Admin Create API
# -------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_college_admin_api_view(request):
    """Creates a User and attaches them to a College as Master/Staff/Office Admin."""
    serializer = CreateCollegeAdminSerializer(data=request.data)
    if serializer.is_valid():
        result = serializer.save()
        return Response(
            {"success": True, "message": "College Admin created successfully.", "data": result},
            status=status.HTTP_201_CREATED
        )
    return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


# -------------------------------------------------------------------
# 3. College Admin - Create Staff API
# -------------------------------------------------------------------

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsMasterOrOfficeAdmin])
def create_staff_profile(request):
    serializer = StaffProfileSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# -------------------------------------------------------------------
# 4. College Admin - Department List
# -------------------------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def department_list(request):
    if request.method == 'GET':
        departments = Department.objects.annotate(staff_count=Count('staff_members', distinct=True),student_count=Count('students', distinct=True)  ) # Replace 'students' with your actual related_name from Student model if different
        serializer = DepartmentSerializer(departments, many=True)
        return render(request, "Admin/department_list.html",{"departments":serializer.data})

    elif request.method == 'POST':
        serializer = DepartmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    
    

# ---------------------------------------------------------------- pages
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_profile_view(request):
    m = get_membership(request.user)
    if not m:
        return HttpResponse("No admin/staff profile found for this account.", status=404)
    return render(request, "Admin/profile.html", {"profile": build_profile(m),"active_nav": "profile",})
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_settings_view(request):
    m = get_membership(request.user)
    if not m:
        return HttpResponse("No admin/staff profile found for this account.", status=404)
    return render(request, "Admin/settings.html", {"profile": build_profile(m),"blood_groups": BLOOD_GROUP_CHOICES,"departments": Department.objects.filter(college=m.college).order_by("name"),"active_nav": "settings",})
 
 
# ---------------------------------------------------------------- APIs
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_profile_update(request):
    m = get_membership(request.user)
    if not m:
        return Response({"detail": "Profile not found."}, status=404)
 
    ser = ProfileSettingsSerializer(m, data=request.data, partial=True, context={"college": m.college})
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response({"detail": "Profile updated successfully."})
 
 
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_password_request_otp(request):
    user = request.user
    if not user.email:
        return Response({"detail": "No email is registered on this account."}, status=400)
 
    # simple 60s resend throttle
    if cache.get(f"{_otp_key(user)}:cooldown"):
        return Response({"detail": "Please wait a minute before requesting another OTP."}, status=429)
 
    otp = f"{secrets.randbelow(10**6):06d}"
    cache.set(_otp_key(user), {"hash": _hash_otp(user, otp), "attempts": 0}, OTP_TTL)
    cache.set(f"{_otp_key(user)}:cooldown", 1, 60)
    send_password_change_otp_email(user, otp)
    
    return Response({"detail": "OTP sent.", "email_hint": mask_email(user.email)})
 
 
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def admin_password_verify_otp(request):
    user = request.user
    otp = str(request.data.get("otp", "")).strip()
    new_password = request.data.get("new_password", "")
    confirm = request.data.get("confirm_password", "")
 
    record = cache.get(_otp_key(user))
    if not record:
        return Response({"detail": "OTP expired or not requested. Please request a new one."}, status=400)
 
    if record["attempts"] >= OTP_MAX_ATTEMPTS:
        cache.delete(_otp_key(user))
        return Response({"detail": "Too many wrong attempts. Please request a new OTP."}, status=400)
 
    if not constant_time_compare(record["hash"], _hash_otp(user, otp)):
        record["attempts"] += 1
        cache.set(_otp_key(user), record, OTP_TTL)
        return Response({"detail": "Invalid OTP."}, status=400)
 
    if new_password != confirm:
        return Response({"detail": "Passwords do not match."}, status=400)
 
    try:
        validate_password(new_password, user)
    except ValidationError as e:
        return Response({"new_password": list(e.messages)}, status=400)
 
    user.set_password(new_password)
    user.save(update_fields=["password"])
    update_session_auth_hash(request, user)      # keep the user logged in
    cache.delete(_otp_key(user))
    return Response({"detail": "Password changed successfully."})
 
    
# ---------------------------------------------------------------------------
# Who is allowed to edit a department's own fields
# ---------------------------------------------------------------------------
def _can_edit_department(request_user, college_user, department):
    # Office Admin / Master Admin ("Principal" — no separate role exists yet,
    # so highest-privilege role stands in for it) can edit any department.
    if college_user.role in ("master_admin", "office_admin"):
        return True

    # HOD can edit only their own department
    staff_profile = StaffProfile.objects.filter(college_user=college_user, is_active=True).first()
    if staff_profile and staff_profile.staff_role == "hod" and staff_profile.department_id == department.id:
        return True

    return False


# ---------------------------------------------------------------------------
# Department detail — editable core fields + HOD / Faculty roster
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def department_detail(request, department_id):
    college_user = CollegeUser.objects.get(user=request.user)
    department = get_object_or_404(Department, id=department_id, college=college_user.college)
    can_edit = _can_edit_department(request.user, college_user, department)
    staff_qs = (StaffProfile.objects.filter(department=department, is_active=True).select_related("college_user__user").order_by("staff_role", "college_user__user__first_name"))
    hod = [s for s in staff_qs if s.staff_role == "hod"]
    class_advisors = [s for s in staff_qs if s.staff_role == "class_advisor"]
    faculty = [s for s in staff_qs if s.staff_role == "staff"]
    student_count = StudentProfile.objects.filter(department=department, is_active=True).count()
    context = {"department": department,"can_edit": can_edit,"hod": hod,"class_advisors": class_advisors,"faculty": faculty,"staff_total": staff_qs.count(),"student_count": student_count,}
    return render(request, "Admin/department_details.html", context)


# ---------------------------------------------------------------------------
# Save department field edits
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_department(request, department_id):
    college_user = CollegeUser.objects.get(user=request.user)
    department = get_object_or_404(Department, id=department_id, college=college_user.college)

    if not _can_edit_department(request.user, college_user, department):
        return Response({"detail": "You don't have permission to edit this department."}, status=status.HTTP_403_FORBIDDEN)

    serializer = DepartmentUpdateSerializer(department, data=request.data, partial=True)
    if serializer.is_valid():
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "One or more codes already exist for this college."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Department updated.", "department": DepartmentUpdateSerializer(department).data}, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# -------------------------------------------------------------------
# 4. College Admin - Department Create API
# -------------------------------------------------------------------
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def department_list_create(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if request.method == 'GET':
        return render(request, "Admin/create_department.html", {"college": college_user.college_id})
    # ---- POST ----
    rows = request.data if isinstance(request.data, list) else [request.data]
    rows = [{**row, "college": college_user.college_id} for row in rows]
    serializer = DepartmentSerializer(data=rows, many=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    codes = [r["code"] for r in serializer.validated_data]
    existing = set(Department.objects.filter(college=college_user.college, code__in=codes).values_list("code", flat=True))
    seen, row_errors, has_error = set(), [], False
    for code in codes:
        if code in existing:
            row_errors.append({"code": [f"Code '{code}' already exists in this college."]})
            has_error = True
        elif code in seen:
            row_errors.append({"code": [f"Code '{code}' is repeated in this form."]})
            has_error = True
        else:
            row_errors.append({})
        seen.add(code)
    if has_error:
        return Response(row_errors, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():
            serializer.save()
    except IntegrityError:
        return Response({"detail": "One or more codes already exist for this college."},status=status.HTTP_400_BAD_REQUEST,)
    messages.success(request, f"{len(codes)} department(s) created successfully")
    return Response({"created": len(codes)}, status=status.HTTP_201_CREATED)
# -------------------------------------------------------------------
# 4. College Admin 
# -------------------------------------------------------------------

DASHBOARD_TITLES = {
    MASTER_ADMIN: "Master Admin Dashboard",
    OFFICE_ADMIN: "Office Admin Dashboard",
    FINANCE_ADMIN: "Finance Dashboard",
    (STAFF_ADMIN, HOD): "HOD Dashboard",
    (STAFF_ADMIN, CLASS_ADVISOR): "Class Advisor Dashboard",
    (STAFF_ADMIN, STAFF): "Staff Dashboard",
}


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def college_admin_dashboard(request):
    if request.method == 'GET':
        college_user = get_college_user(request)
 
        if college_user is None or college_user.college is None:
            return render(request, "Admin/admin_dashboard.html", {
                "college": None, "dashboard_title": "Dashboard",
                "sections": get_dashboard_sections(None, None),
                "kpi_cards": [],
                "master_admin": {"name": request.user.get_full_name() or request.user.email, "employee_id": ""},
            })
 
        context = build_dashboard_context(request, college_user)
        return render(request, "Admin/admin_dashboard.html", context)
 
    elif request.method == 'POST':
        # NOTE: still looks misplaced on a dashboard view — see earlier note.
        serializer = DepartmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
 
 
# ---------------------------------------------------------------------------
# Section visibility per role — the single source of truth the template
# branches on. Nothing else in this file should hardcode "if role == ...";
# route it through sections.
# ---------------------------------------------------------------------------
SECTION_KEYS = (
    "kpis", "departments_overview", "quick_actions", "staff_directory",
    "fee_collection", "fee_by_department", "recent_payments", "recent_batches",
    "own_department", "own_class", "today_timetable", "take_attendance",
    "attendance_overview",
)
 
 
def get_dashboard_sections(role, staff_role=None):
    sections = {key: False for key in SECTION_KEYS}
 
    if role == MASTER_ADMIN:
        for key in ("kpis", "departments_overview", "quick_actions", "staff_directory",
                    "fee_collection", "fee_by_department", "recent_payments", "recent_batches"):
            sections[key] = True
 
    elif role == OFFICE_ADMIN:
        for key in ("kpis", "departments_overview", "quick_actions", "staff_directory"):
            sections[key] = True
 
    elif role == FINANCE_ADMIN:
        for key in ("kpis", "fee_collection", "fee_by_department", "recent_payments", "recent_batches"):
            sections[key] = True
 
    elif role == STAFF_ADMIN:
        if staff_role == HOD:
            for key in ("kpis", "quick_actions", "staff_directory", "own_department",
                        "today_timetable", "attendance_overview"):
                sections[key] = True
        elif staff_role == CLASS_ADVISOR:
            for key in ("kpis", "own_class", "today_timetable", "take_attendance"):
                sections[key] = True
        elif staff_role == STAFF:
            for key in ("kpis", "today_timetable", "take_attendance"):
                sections[key] = True
 
    return sections
 
 
# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def build_dashboard_context(request, college_user):
    role = college_user.role
    staff_role = None
    if role == STAFF_ADMIN:
        staff_profile = getattr(college_user, "staff_profile", None)
        staff_role = staff_profile.staff_role if staff_profile else None
 
    sections = get_dashboard_sections(role, staff_role)
    title = DASHBOARD_TITLES.get((role, staff_role) if role == STAFF_ADMIN else role, "Dashboard")
 
    base_context = {"college": college_user.college,"master_admin": _admin_display(college_user),"dashboard_title": title,"dashboard_role": role,"staff_role": staff_role,"sections": sections,}
 
    if role == MASTER_ADMIN:
        base_context.update(_master_admin_data(college_user.college))
    elif role == OFFICE_ADMIN:
        base_context.update(_office_admin_data(college_user.college))
    elif role == FINANCE_ADMIN:
        base_context.update(_finance_admin_data(college_user.college))
    elif role == STAFF_ADMIN and staff_role == HOD:
        base_context.update(_hod_data(college_user))
    elif role == STAFF_ADMIN and staff_role == CLASS_ADVISOR:
        base_context.update(_advisor_data(college_user))
    elif role == STAFF_ADMIN and staff_role == STAFF:
        base_context.update(_staff_data(college_user, request.user))
    else:
        base_context["kpi_cards"] = []
 
    return base_context
 
 
def _admin_display(college_user):
    u = college_user.user
    return {
        "name": u.get_full_name() or u.email,
        "employee_id": college_user.employee_or_student_id or "EMP-0001",
    }
 
 
# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------
def _people_counts(college):
    return {"total_members": college.users.exclude(status="remove").count(),"total_students": StudentProfile.objects.filter(college=college, is_active=True).count(),"total_staff": StaffProfile.objects.filter(college_user__college=college, is_active=True).count(),"total_hods": StaffProfile.objects.filter(college_user__college=college, staff_role="hod", is_active=True).count(),"total_class_advisors": StaffProfile.objects.filter(college_user__college=college, staff_role="class_advisor", is_active=True).count(),"total_office_admins": college.users.filter(role="office_admin", status="active").count(),}
 
 
def _department_breakdown(college, department_filter=None):
    depts = Department.objects.filter(college=college, is_active=True)
    if department_filter is not None:
        depts = depts.filter(pk=department_filter)
    out = []
    for dept in depts:
        student_count = StudentProfile.objects.filter(department=dept, is_active=True).count()
        staff_count = StaffProfile.objects.filter(department=dept, is_active=True).count()
        year_rows = (StudentProfile.objects.filter(department=dept, is_active=True).values("year").annotate(count=Count("id")))
        year_map = {row["year"]: row["count"] for row in year_rows if row["year"]}
        out.append({"name": dept.name, "code": dept.code, "id": dept.id,"student_count": student_count, "staff_count": staff_count,"year_breakdown": [{"year": y, "count": year_map.get(y, 0)} for y in (1, 2, 3, 4)],})
    return out
 
 
def _staff_directory(college, department=None, limit=10):
    qs = StaffProfile.objects.filter(college_user__college=college, is_active=True)
    if department is not None:
        qs = qs.filter(department=department)
    qs = qs.select_related("college_user__user", "department").order_by("-created_at")[:limit]
    out = []
    for sp in qs:
        u = sp.college_user.user
        out.append({"name": u.get_full_name() or u.email,"staff_role": sp.get_staff_role_display(),"department": sp.department.short_name if sp.department else None,"designation": sp.designation,"employee_id": sp.college_user.employee_or_student_id or "—","status": sp.college_user.status,})
    return out
 
 
def _fee_snapshot(college):
    current = AcademicYear.objects.filter(college=college, is_current=True).first()
    academic_year = current.name if current else (StudentFeeInvoice.objects.filter(fee_structure__college=college).order_by("-academic_year").values_list("academic_year", flat=True).first())
    invoices_qs = (StudentFeeInvoice.objects.filter(fee_structure__college=college, academic_year=academic_year).exclude(status="cancelled") if academic_year else StudentFeeInvoice.objects.none())
 
    billed_agg = invoices_qs.aggregate(gross=Sum("total_amount"), discount=Sum("discount_amount"))
    total_billed = (billed_agg["gross"] or 0) - (billed_agg["discount"] or 0)
    total_collected = FeePayment.objects.filter(
        invoice__in=invoices_qs, status="success").aggregate(total=Sum("amount"))["total"] or 0
    fee_collection_percent = round((total_collected / total_billed) * 100) if total_billed else 0
    fee_paid_count = invoices_qs.filter(status="paid").values("student").distinct().count()
    fee_pending_count = invoices_qs.filter(status__in=["pending", "partial", "overdue"]).values("student").distinct().count()
 
    fee_pending = []
    pending_invoices = (invoices_qs.filter(status__in=["pending", "partial", "overdue"]).select_related("student__college_user__user", "fee_structure__department").order_by("due_date")[:8])
    for inv in pending_invoices:
        su = inv.student.college_user.user
        fee_pending.append({"name": su.get_full_name() or su.email,"admission_number": inv.student.admission_number,"department": inv.fee_structure.department.short_name if inv.fee_structure.department else "All Depts","year": inv.fee_structure.year,"amount_due": inv.balance_due,})
 
    dept_invoice_stats = (invoices_qs.values("fee_structure__department_id", "fee_structure__department__name").annotate(total_students=Count("student", distinct=True),paid_students=Count("student", filter=Q(status="paid"), distinct=True)))
    dept_collected_rows = (FeePayment.objects.filter(invoice__in=invoices_qs, status="success").values("invoice__fee_structure__department_id").annotate(collected=Sum("amount")))
    collected_by_dept = {r["invoice__fee_structure__department_id"]: r["collected"] for r in dept_collected_rows}
    fee_by_department = [{"department": row["fee_structure__department__name"] or "All Departments","total_students": row["total_students"],"paid_students": row["paid_students"],"collected_amount": collected_by_dept.get(row["fee_structure__department_id"], 0),} for row in dept_invoice_stats]
 
    last_payments = []
    for p in (FeePayment.objects.filter(invoice__fee_structure__college=college, status="success")
              .select_related("student__college_user__user", "invoice").order_by("-paid_at")[:8]):
        su = p.student.college_user.user
        last_payments.append({"student_name": su.get_full_name() or su.email, "admission_number": p.student.admission_number,"amount": p.amount, "payment_mode": p.get_payment_mode_display(),"receipt_number": p.receipt_number, "invoice_number": p.invoice.invoice_number, "paid_at": p.paid_at,})
 
    last_batches = []
    for b in SettlementBatch.objects.filter(college=college).order_by("-created_at")[:5]:
        last_batches.append({"batch_number": b.batch_number, "status": b.get_status_display(), "status_raw": b.status,"total_amount": b.total_amount, "total_transactions": b.total_transactions,"settlement_date": b.settlement_date, "utr_number": b.utr_number,})
 
    return {"academic_year": academic_year,"fee_collection_percent": fee_collection_percent,"fee_paid_count": fee_paid_count,"fee_pending_count": fee_pending_count,"fee_pending": fee_pending,"fee_by_department": fee_by_department,"last_payments": last_payments,"last_batches": last_batches,}
 
 
def _today_timetable_rows(slots_qs):
    today = timezone.now().date()
    rows = []
    for slot in slots_qs.select_related("classroom", "subject_mapping__subject", "teacher").order_by("period_number"):
        session = PeriodAttendanceSession.objects.filter(timetable_slot=slot, date=today).first()
        rows.append({"period_number": slot.period_number,"subject": slot.subject_mapping.subject.name,"classroom": slot.classroom.name,"start_time": slot.start_time,"end_time": slot.end_time,"teacher": slot.teacher.get_full_name() if slot.teacher else "—","attendance_taken": bool(session and session.is_completed),"slot_id": slot.id,})
    return rows
 
 
def _today_day_of_week():
    dow = timezone.now().isoweekday()  # Mon=1 .. Sun=7
    return dow if dow in range(1, 7) else None  # Sunday -> no periods (1-6 only in DAYS_OF_WEEK)
 
 
# ---------------------------------------------------------------------------
# Per-role context builders
# ---------------------------------------------------------------------------
def _master_admin_data(college):
    counts = _people_counts(college)
    fee = _fee_snapshot(college)
    stats = {**counts, "fee_collection_percent": fee["fee_collection_percent"],
             "fee_paid_count": fee["fee_paid_count"], "fee_pending_count": fee["fee_pending_count"],
             "academic_year": fee["academic_year"]}
    expected_amount = StudentFeeInvoiceItem.objects.filter(invoice__student__college=college).aggregate(total=Sum("amount"))["total"] or 0
    paid_amount = FeePayment.objects.filter(invoice__student__college=college, status="success").aggregate(total=Sum("amount"))["total"] or 0
    pending_amount = expected_amount - paid_amount
    collection_percent = round((paid_amount / expected_amount) * 100, 1) if expected_amount else 0

    return {
        "stats": stats,
        "kpi_cards": [
            {"icon": "expected", "label": "Expected Amount", "value": f"₹{expected_amount:,.0f}"},
            {"icon": "paid", "label": "Paid Amount", "value": f"₹{paid_amount:,.0f}"},
            {"icon": "pending", "label": "Pending Amount", "value": f"₹{pending_amount:,.0f}"},
            {"icon": "fee_percent", "label": "Collection %", "value": f"{collection_percent}%"},
        ],
        "departments": _department_breakdown(college),
        "staff_directory": _staff_directory(college),
        "fee_pending": fee["fee_pending"],
        "fee_by_department": fee["fee_by_department"],
        "last_payments": fee["last_payments"],
        "last_batches": fee["last_batches"],
    }
 
 
def _office_admin_data(college):
    counts = _people_counts(college)
    return {
        "stats": counts,
        "kpi_cards": [
            {"icon": "students", "label": "Total Students", "value": counts["total_students"]},
            {"icon": "staff", "label": "Total Staff", "value": counts["total_staff"]},
            {"icon": "hod", "label": "HODs", "value": counts["total_hods"]},
            {"icon": "advisor", "label": "Class Advisors", "value": counts["total_class_advisors"]},
        ],
        "departments": _department_breakdown(college),
        "staff_directory": _staff_directory(college),
        # deliberately no fee_* / attendance keys — office_admin has no fee or attendance access
    }
 
 
def _finance_admin_data(college):
    fee = _fee_snapshot(college)
    total_students = StudentProfile.objects.filter(college=college, is_active=True).count()
    return {
        "stats": {"total_students": total_students, **fee},
        "kpi_cards": [
            {"icon": "students", "label": "Total Students", "value": total_students},
            {"icon": "fee_percent", "label": "Fee Collected", "value": f'{fee["fee_collection_percent"]}%'},
            {"icon": "paid", "label": "Students Paid", "value": fee["fee_paid_count"]},
            {"icon": "pending", "label": "Students Pending", "value": fee["fee_pending_count"]},
        ],
        "fee_pending": fee["fee_pending"],
        "fee_by_department": fee["fee_by_department"],
        "last_payments": fee["last_payments"],
        "last_batches": fee["last_batches"],
        # no departments / staff_directory / quick_actions — finance_admin is fee + read-only students only
    }
 
 
def _hod_data(college_user):
    staff_profile = college_user.staff_profile
    dept = staff_profile.department
 
    if dept is None:
        return {"stats": {}, "kpi_cards": [], "own_department": None, "today_timetable": [],
                "staff_directory": [], "attendance_overview": []}
 
    dept_data = _department_breakdown(college_user.college, department_filter=dept.id)
    dept_summary = dept_data[0] if dept_data else None
 
    subject_count = DepartmentSubjectMapping.objects.filter(department=dept).count()
    classrooms = Classroom.objects.filter(department=dept)
 
    today_dow = _today_day_of_week()
    today_timetable = []
    attendance_overview = []
    if today_dow:
        slots_qs = TimetableSlot.objects.filter(classroom__in=classrooms, day_of_week=today_dow)
        today_timetable = _today_timetable_rows(slots_qs)
        for row in today_timetable:
            attendance_overview.append(row)  # same rows double as "who's completed attendance today"
 
    return {
        "stats": {
            "dept_student_count": dept_summary["student_count"] if dept_summary else 0,
            "dept_staff_count": dept_summary["staff_count"] if dept_summary else 0,
            "dept_subject_count": subject_count,
            "dept_classroom_count": classrooms.count(),
        },
        "kpi_cards": [
            {"icon": "students", "label": "Department Students", "value": dept_summary["student_count"] if dept_summary else 0},
            {"icon": "staff", "label": "Department Staff", "value": dept_summary["staff_count"] if dept_summary else 0},
            {"icon": "subjects", "label": "Subjects", "value": subject_count},
            {"icon": "classrooms", "label": "Classrooms", "value": classrooms.count()},
        ],
        "own_department": dept_summary,
        "staff_directory": _staff_directory(college_user.college, department=dept),
        "today_timetable": today_timetable,
        "attendance_overview": attendance_overview,
    }
 
 
def _advisor_data(college_user):
    staff_profile = college_user.staff_profile
    dept = staff_profile.department
    year = staff_profile.advisor_year
 
    if dept is None or year is None:
        return {"stats": {}, "kpi_cards": [], "own_class": None, "today_timetable": []}
 
    students_qs = StudentProfile.objects.filter(department=dept, year=year, is_active=True)
    student_count = students_qs.count()
    classrooms = Classroom.objects.filter(department=dept, year=year)
 
    today_dow = _today_day_of_week()
    today_timetable = _today_timetable_rows(
        TimetableSlot.objects.filter(classroom__in=classrooms, day_of_week=today_dow)
    ) if today_dow else []
    pending_today = sum(1 for row in today_timetable if not row["attendance_taken"])
 
    own_class = {
        "department": dept.name, "year": year, "student_count": student_count,
        "classrooms": [c.name for c in classrooms],
        "students": [
            {"name": s.college_user.user.get_full_name() or s.college_user.user.email,
             "admission_number": s.admission_number, "roll_number": s.roll_number, "section": s.section}
            for s in students_qs.select_related("college_user__user")[:20]
        ],
    }
 
    return {
        "stats": {"class_student_count": student_count, "today_periods_count": len(today_timetable),
                  "pending_attendance_today": pending_today},
        "kpi_cards": [
            {"icon": "students", "label": "My Class Students", "value": student_count},
            {"icon": "periods", "label": "Periods Today", "value": len(today_timetable)},
            {"icon": "pending", "label": "Attendance Pending", "value": pending_today},
        ],
        "own_class": own_class,
        "today_timetable": today_timetable,
    }
 
 
def _staff_data(college_user, user):
    today_dow = _today_day_of_week()
    today_timetable = _today_timetable_rows(
        TimetableSlot.objects.filter(teacher=user, day_of_week=today_dow)
    ) if today_dow else []
    taken = sum(1 for row in today_timetable if row["attendance_taken"])
    pending = len(today_timetable) - taken
 
    return {
        "stats": {"today_periods_count": len(today_timetable), "attendance_taken_count": taken,
                  "attendance_pending_count": pending},
        "kpi_cards": [
            {"icon": "periods", "label": "Periods Today", "value": len(today_timetable)},
            {"icon": "paid", "label": "Attendance Marked", "value": taken},
            {"icon": "pending", "label": "Attendance Pending", "value": pending},
        ],
        "today_timetable": today_timetable,
    }
    
    
    
      
#office admin list
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def college_office_admins(request):
    if request.method == "GET":
        requesting_college_user = CollegeUser.objects.get(user=request.user)
        office_admins = CollegeUser.objects.filter(role='office_admin')
        can_edit = _can_edit_office_admin(requesting_college_user)
        for admin in office_admins:
            try:
                admin.dept = Department.objects.get(id=admin.department).name
            except:
                admin.dept = admin.department
        context = {"office_admins":office_admins,"can_edit":can_edit}
        print(context)
        return render(request, 'Admin/office_admins.html', context)
    

#create office admin api
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def create_office_admins(request):
    college_user = CollegeUser.objects.get(user=request.user)

    def render_form(form_data=None, status_code=200):
        departments = Department.objects.filter(is_active=True, college=college_user.college)
        return render(request,"Admin/create_office_admin.html",{"departments": departments,"college": college_user.college_id,"form_data": form_data or {},"blood_groups": BLOOD_GROUP_CHOICES,},status=status_code,)

    if request.method == "GET":
        return render_form()

    data = request.data.copy()
    data["college"] = str(college_user.college_id)

    serializer = OfficeAdminCreateSerializer(data=data)
    if not serializer.is_valid():
        messages.error(request, " | ".join(_flatten_errors(serializer.errors)) or "Please check the entered details and try again.")
        return render_form(request.POST, 400)
    try:
        with transaction.atomic():
            office_admin = serializer.save()
    except IntegrityError:
        messages.error(request, "An account with this email or employee ID already exists.")
        return render_form(request.POST, 400)
    except Exception:
        logger.exception("Office admin creation failed")
        messages.error(request, "Something went wrong while creating the office admin. Please try again.")
        return render_form(request.POST, 500)

    user = office_admin.user
    full_name = f"{user.first_name} {user.last_name}".strip() or user.email
    try:
        staff_create_account(staff_name=full_name,staff_email=user.email,temporary_password=office_admin.generated_password,)
    except Exception:
        logger.exception("Welcome email failed for office admin %s", office_admin.pk)
        messages.warning(request, "Office Admin created, but the login email could not be sent.")
        return redirect("college-office-admin")

    messages.success(request, "Office Admin created successfully.")
    return redirect("college-office-admin")

# ---------------------------------------------------------------------------
# Who can edit an office admin's details
# ---------------------------------------------------------------------------
def _can_edit_office_admin(requesting_college_user):
    return requesting_college_user.role in ("master_admin", "office_admin")


# ---------------------------------------------------------------------------
# Office admin detail
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def office_admin_detail(request, office_admin_id):
    requesting_college_user = CollegeUser.objects.get(user=request.user)
    office_admin = get_object_or_404(CollegeUser.objects.select_related("user"),id=office_admin_id,role="office_admin",college=requesting_college_user.college,)
    can_edit = _can_edit_office_admin(requesting_college_user)
    departments = Department.objects.filter(is_active=True, college=requesting_college_user.college)
    context = {"office_admin": office_admin,"can_edit": can_edit,"departments": departments,"role_choices": CollegeUser.ROLE_CHOICES,"status_choices": CollegeUser.STATUS_CHOICES,}
    return render(request, "Admin/office_admin_detail.html", context)


# ---------------------------------------------------------------------------
# Save office admin edits
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_office_admin(request, office_admin_id):
    requesting_college_user = CollegeUser.objects.get(user=request.user)
    office_admin = get_object_or_404(CollegeUser.objects.select_related("user"),id=office_admin_id, role="office_admin",college=requesting_college_user.college,)
    if not _can_edit_office_admin(requesting_college_user):
        return Response({"detail": "You don't have permission to edit office admin details."},status=status.HTTP_403_FORBIDDEN)
    serializer = OfficeAdminUpdateSerializer(office_admin, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    send_pw = serializer.validated_data.get("send_password", False)
    password_sent = False
    try:
        with transaction.atomic():
            serializer.save()
            office_admin.refresh_from_db()
            user = office_admin.user
            if send_pw:
                new_password = _generate_password()
                user.set_password(new_password)
                user.save(update_fields=["password"])
                staff_create_account(user.first_name, user.email, new_password, login_url="http:192.168.1.22")
                password_sent = True
    except IntegrityError:
        return Response({"detail": "Email or mobile number already in use."},status=status.HTTP_400_BAD_REQUEST)
    except (smtplib.SMTPException, OSError):
        return Response({"detail": "Could not send the email, so no changes were saved. Check the email address and try again."},status=status.HTTP_502_BAD_GATEWAY)
    return Response({"message": "Office Admin updated.","password_sent": password_sent,"status": office_admin.status,"department": office_admin.department,"role": office_admin.role,"first_name": user.first_name,"last_name": user.last_name,"email": user.email,"mobile_number": user.mobile_number,}, status=status.HTTP_200_OK)
    
# ---------------------------------------------------------------------------
# Staff list — department-wise, HOD shown separately from regular staff
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    can_edit = _can_edit_office_admin(college_user)
    departments = (Department.objects.filter(is_active=True, college=college_user.college).prefetch_related("staff_members__college_user__user").order_by("name"))
    department_groups = []
    for dept in departments:
        active_staff = dept.staff_members.all().select_related("college_user", "college_user__user")
        print(active_staff)
        hod = active_staff.filter(staff_role="hod").first()
        staff_members = active_staff.exclude(staff_role="hod").order_by("staff_role", "college_user__user__first_name")
        department_groups.append({"department": dept,"hod": hod,"staff": staff_members,"staff_count": staff_members.count(),})
    context = {"department_groups": department_groups,"college_user":college_user,"can_edit":can_edit}
    return render(request, "Admin/staff_list.html", context)
 
 
# JSON variant of the same data, for the mobile / API client
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_list_api(request):
    college_user = CollegeUser.objects.get(user=request.user)
    departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    data = []
    for dept in departments:
        active_staff = dept.staff_members.filter(is_active=True).select_related("college_user", "college_user__user")
        hod = active_staff.filter(staff_role="hod").first()
        staff_members = active_staff.exclude(staff_role="hod")
        data.append({"department_id": dept.id,"department_name": dept.name,"hod": StaffListSerializer(hod).data if hod else None,"staff": StaffListSerializer(staff_members, many=True).data,})
    return Response(data, status=status.HTTP_200_OK)
 
# ---------------------------------------------------------------------------
# Create staff — GET renders the form, POST creates the account
# ---------------------------------------------------------------------------

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated, IsMasterAdmin])
def create_staff(request):
    college_user = CollegeUser.objects.get(user=request.user)
    def render_form(form_data=None, status_code=200):
        departments = Department.objects.filter(is_active=True, college=college_user.college)
        return render(request,"Admin/create_staff.html",{"year_choices": YEAR_CHOICES,"departments": departments,"college": college_user.college_id,"form_data": form_data or {},"blood_groups": BLOOD_GROUP_CHOICES,},status=status_code,)

    if request.method == "GET":
        return render_form()
    data = request.data.copy()
    data["college"] = str(college_user.college_id)

    serializer = StaffCreateSerializer(data=data)
    if not serializer.is_valid():
        messages.error(request, " | ".join(_flatten_errors(serializer.errors)) or "Please check the entered details and try again.")
        return render_form(request.POST, 400)

    try:
        with transaction.atomic():
            staff_profile = serializer.save()
    except IntegrityError:
        messages.error(request,"An account with this email or employee ID already exists, " "or this department already has an active HOD.",)
        return render_form(request.POST, 400)
    except Exception:
        logger.exception("Staff creation failed")
        messages.error(request, "Something went wrong while creating the staff member. Please try again.")
        return render_form(request.POST, 500)

    user = staff_profile.college_user.user
    full_name = f"{user.first_name} {user.last_name}".strip() or user.email
    try:
        staff_create_account(staff_name=full_name,staff_email=user.email,temporary_password=staff_profile.generated_password,)
    except Exception:
        logger.exception("Welcome email failed for staff %s", staff_profile.pk)
        messages.warning(request, "Staff created, but the login email could not be sent.")
        return redirect("college-staff")

    messages.success(request, "Staff created successfully.")
    return redirect("college-staff")
# ---------------------------------------------------------------------------
# Create staff bulk using .xlsx sheet
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMasterAdmin])
def bulk_create_staff(request):
    serializer = BulkStaffUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    file = request.FILES["file"]
    college_id = request.data.get("college")
    try:
        college = College.objects.get(id=college_id)
    except College.DoesNotExist:
        return Response({"error": "Invalid college ID"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        df = pd.read_excel(file)
        # Convert NaN values to empty strings or None
        df = df.fillna('')
    except Exception as e:
        return Response({"error": f"Failed to parse Excel file: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
    created_staff = []
    errors = []
    # Map departments for rapid lookup
    departments = {dept.name.lower(): dept for dept in Department.objects.filter(college=college, is_active=True)}
    for index, row in df.iterrows():
        row_num = index + 2  # Adjust for 1-based index and header row
        email = str(row.get("email", "")).strip()
        dept_name = str(row.get("department", "")).strip().lower()
        if not email:
            errors.append(f"Row {row_num}: Email is required.")
            continue
        if dept_name not in departments:
            errors.append(f"Row {row_num}: Department '{row.get('department')}' not found.")
            continue
        department = departments[dept_name]
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        generated_password = get_random_string(length=10, allowed_chars=chars)
        data = {"college": college.id,"first_name": str(row.get("first_name", "")).strip(),"last_name": str(row.get("last_name", "")).strip(),"email": str(row.get("email", "")).strip(),"mobile_number": str(row.get("mobile_number", "")).strip(),"password": generated_password,"date_of_birth": (str(row.get("date_of_birth", "")).strip() or None ),"blood_group": str(row.get("blood_group", "")).strip() or None,"emergency_contact_number": (str(row.get("emergency_contact_number", "")).strip() or None),"address": str(row.get("address", "")).strip() or None,"work_experience": (str(row.get("work_experience", "")).strip() or ""),"employee_or_student_id": str(row.get("employee_id", "")).strip(),"department": department.id,"staff_role": str(row.get("staff_role", "staff")).strip().lower(),"designation": str(row.get("designation", "")).strip(),"joining_date": str(row.get("joining_date", "")).strip() or None,}
        staff_serializer = StaffCreateSerializer(data=data)
        if staff_serializer.is_valid():
            try:
                with transaction.atomic():
                    staff_profile = staff_serializer.save()
                    full_name = f"{str(row.get("first_name", "")).strip()} {str(row.get("last_name", "")).strip()}".strip() or email
                    staff_create_account(staff_name=full_name,staff_email=email,temporary_password=generated_password) # Or your frontend reset link
                    created_staff.append(staff_profile.college_user.user.email)
            except Exception as e:
                errors.append(f"Row {row_num}: Database error ({str(e)})")
        else:
            errors.append(f"Row {row_num}: {staff_serializer.errors}")
    messages.success(request,f"Successfully created {len(created_staff)} staff members.")
    return redirect("create-staff")
    return Response({"message": f"Successfully created {len(created_staff)} staff members.","created_count": len(created_staff),"errors": errors}, status=status.HTTP_207_MULTI_STATUS if errors else status.HTTP_201_CREATED)

# ---------------------------------------------------------------------------
# Download sample staff .xlsx file
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated, IsMasterAdmin])
def download_staff_sample(request):
    columns = ["first_name", "last_name", "email", "mobile_number", "blood_group","date_of_birth", "address","emergency_contact_number", "employee_id", "department", "staff_role", "designation", "joining_date"]
    sample_data = [{"first_name": "John","last_name": "Doe","email": "sample@example.com","mobile_number": "+910123456789","blood_group": "O+","date_of_birth":"01-01-2000", "address": "123 ABC Street, City","emergency_contact_number":"0123456789","work_experience":"2 years","employee_id": "ST-1001","department": "Computer Science","staff_role": "staff","designation": "Assistant Professor","joining_date": "2024-01-01"}]  # 'hod', 'class_advisor', or 'staff'
    df = pd.DataFrame(sample_data, columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Staff Upload Template')
    output.seek(0)
    response = HttpResponse(output.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="staff_upload_sample.xlsx"'
    return response



# ---------------------------------------------------------------------------
# Who can edit a staff member's details / subject assignments
# ---------------------------------------------------------------------------
from django.db import transaction, IntegrityError

def _can_edit_staff(requesting_college_user):
    return requesting_college_user.role in ("master_admin", "office_admin")


# ---------------------------------------------------------------------------
# Staff detail — basic profile + subjects taught
# ---------------------------------------------------------------------------
def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"
    
YEAR_CHOICES = [(1, '1st Year'), (2, '2nd Year'), (3, '3rd Year'), (4, '4th Year')]
SEMESTER_CHOICES = [(i, f"{get_ordinal(i)} Semester") for i in range(1, 9)]
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def staff_detail(request, staff_id):
    requesting_college_user = CollegeUser.objects.get(user=request.user)
    staff = get_object_or_404(StaffProfile.objects.select_related("college_user__user", "department"),id=staff_id, college_user__college=requesting_college_user.college,)
    can_edit = _can_edit_staff(requesting_college_user)
    assigned_mappings = (DepartmentSubjectMapping.objects.filter(teacher=staff).select_related("subject", "department").order_by("department__name", "year", "semester"))
    available_mappings = (DepartmentSubjectMapping.objects.filter(department=staff.department).exclude(teacher=staff).select_related("subject", "department").order_by("year", "semester", "subject__name") if staff.department_id else DepartmentSubjectMapping.objects.none())

    departments = Department.objects.filter(is_active=True, college=requesting_college_user.college)
    context = {"staff": staff,"can_edit": can_edit,"assigned_mappings": assigned_mappings,"year_choices":YEAR_CHOICES,"available_mappings": available_mappings,"departments": departments,"staff_role_choices": StaffProfile.STAFF_ROLE_CHOICES,"status_choices": CollegeUser.STATUS_CHOICES,}
    return render(request, "Admin/staff_detail.html", context)


# ---------------------------------------------------------------------------
# Save basic staff/profile edits
# ---------------------------------------------------------------------------

def _generate_password(length=10):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return get_random_string(length=length, allowed_chars=chars)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_staff(request, staff_id):
    requesting_college_user = CollegeUser.objects.get(user=request.user)
    staff = get_object_or_404(StaffProfile.objects.select_related("college_user__user"),id=staff_id, college_user__college=requesting_college_user.college,)
    if not _can_edit_staff(requesting_college_user):
        return Response({"detail": "You don't have permission to edit staff details."},status=status.HTTP_403_FORBIDDEN)
    serializer = StaffUpdateSerializer(staff, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    send_pw = serializer.validated_data.get("send_password", False)
    password_sent = False
    try:
        with transaction.atomic():
            serializer.save()
            staff.refresh_from_db()
            user = staff.college_user.user
            if send_pw:
                new_password = _generate_password()
                user.set_password(new_password)
                user.save(update_fields=["password"])
                staff_create_account(user.first_name, user.email, new_password, login_url="http:192.168.1.22")
                password_sent = True
    except IntegrityError:
        return Response({"detail": "Email or mobile number already in use."},status=status.HTTP_400_BAD_REQUEST)
    except (smtplib.SMTPException, OSError):
        # transaction rolled back: email and password are unchanged
        return Response({"detail": "Could not send the email, so no changes were saved. Check the email address and try again."},status=status.HTTP_502_BAD_GATEWAY)
    return Response({"message": "Staff updated.","password_sent": password_sent,"staff_role": staff.staff_role,"designation": staff.designation,"department": staff.department.name if staff.department_id else None,"advisor_year": staff.get_advisor_year_display() if staff.advisor_year else None,"status": staff.college_user.status,"first_name": user.first_name,"last_name": user.last_name,"email": user.email,"mobile_number": user.mobile_number,}, status=status.HTTP_200_OK)

# ---------------------------------------------------------------------------
# Save subject assignments (checkbox list scoped to staff's current department)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_staff_subjects(request, staff_id):
    requesting_college_user = CollegeUser.objects.get(user=request.user)
    staff = get_object_or_404(StaffProfile.objects.select_related("department"),id=staff_id, college_user__college=requesting_college_user.college,)

    if not _can_edit_staff(requesting_college_user):
        return Response({"detail": "You don't have permission to edit subject assignments."}, status=status.HTTP_403_FORBIDDEN)
    if not staff.department_id:
        return Response({"detail": "Assign a department before managing subjects."}, status=status.HTTP_400_BAD_REQUEST)
    mapping_ids = request.data.get("mapping_ids", [])
    if not isinstance(mapping_ids, list):
        return Response({"detail": "mapping_ids must be a list."}, status=status.HTTP_400_BAD_REQUEST)
    scoped_mappings = DepartmentSubjectMapping.objects.filter(department=staff.department, subject__college=requesting_college_user.college)
    selected = scoped_mappings.filter(id__in=mapping_ids)
    if len(set(mapping_ids)) != selected.count():
        return Response({"detail": "One or more selected subjects are invalid for this department."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        scoped_mappings.filter(teacher=staff).exclude(id__in=mapping_ids).update(teacher=None)
        selected.update(teacher=staff)

    updated = (DepartmentSubjectMapping.objects.filter(teacher=staff).select_related("subject", "department").order_by("department__name", "year", "semester"))
    return Response({
        "message": "Subject assignments updated.",
        "subjects": [
            {"id": str(m.id),"subject": m.subject.name,"department": m.department.name,"year": m.get_year_display(),"semester": m.get_semester_display(),}
            for m in updated
        ],}, status=status.HTTP_200_OK)
 
# ---------------------------------------------------------------------------
# Deactivate / remove staff (used by the "Manage" action in the list page)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsMasterAdmin])
def deactivate_staff(request, staff_id):
    staff_profile = get_object_or_404(StaffProfile, id=staff_id)
    staff_profile.is_active = False
    staff_profile.save(update_fields=["is_active"])
    staff_profile.college_user.status = "inactive"
    staff_profile.college_user.save(update_fields=["status"])
    return Response({"message": "Staff deactivated."}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Subject list — Department -> Semester -> Subjects
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subject_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    # Fetch active departments for the college
    departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    department_groups = []
    for dept in departments:
        mappings = (DepartmentSubjectMapping.objects.filter(department=dept,subject__college=college_user.college,subject__is_active=True,).select_related("subject").order_by("year", "semester", "subject__code"))
        semester_groups = []
        # Group mappings by (year, semester)
        for (year, semester), mappings_in_sem in groupby(
            mappings, key=lambda m: (m.year, m.semester)
        ):
            mappings_list = list(mappings_in_sem)
            first_mapping = mappings_list[0]
            subjects = [m.subject for m in mappings_list]
            semester_groups.append(
                {"year": year,"year_display": first_mapping.get_year_display(),"semester": semester,"semester_display": first_mapping.get_semester_display(),"subjects": subjects,})
        department_groups.append({"department": dept,"semester_groups": semester_groups,"subject_count": mappings.count(),})

    context = {"department_groups": department_groups}
    return render(request, "Admin/subjects_list.html", context)
 
 
# JSON variant — same Department -> Semester -> Subjects shape
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subject_list_api(request):
    college_user = CollegeUser.objects.get(user=request.user)
    departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
 
    data = []
    for dept in departments:
        subjects = Subject.objects.filter(departments=dept, college=college_user.college, is_active=True).order_by("year", "semester", "code")
 
        semesters = []
        for semester, subjects_in_semester in groupby(subjects, key=lambda s: s.semester):
            subjects_in_semester = list(subjects_in_semester)
            semesters.append({"semester": semester,"semester_display": subjects_in_semester[0].get_semester_display(),"subjects": SubjectListSerializer(subjects_in_semester, many=True).data,})
 
        data.append({"department_id": dept.id,"department_name": dept.name,"semesters": semesters,})
 
    return Response(data, status=status.HTTP_200_OK)
 
 
# ---------------------------------------------------------------------------
# Create subject — GET renders the form, POST creates the subject
# ---------------------------------------------------------------------------

def _flatten_errors(errors, prefix=""):
    msgs = []
    if isinstance(errors, dict):
        for key, val in errors.items():
            label = "" if key == "non_field_errors" else f"{key.replace('_', ' ').capitalize()}: "
            msgs += _flatten_errors(val, f"{prefix}{label}")
    elif isinstance(errors, (list, tuple)):
        for item in errors:
            msgs += _flatten_errors(item, prefix)
    else:
        msgs.append(f"{prefix}{errors}")
    return msgs

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def create_subject(request):
    college_user = CollegeUser.objects.get(user=request.user)
    
    def render_form(form_data=None, assignments=None, status_code=200):
        departments = Department.objects.filter(is_active=True, college=college_user.college)
        staff_members = StaffProfile.objects.filter(college_user__college=college_user.college, is_active=True).select_related("college_user__user")
        return render(request,"Admin/create_subject.html",{"departments": departments,"college": college_user.college_id,"staff_members": staff_members,"form_data": form_data or {},"initial_assignments": assignments or [],},status=status_code,)
 
    if request.method == "GET":
        return render_form()
    print(request.data)
    post = request.POST

    # Raw (string) rows, used to rebuild the department rows on error
    raw_assignments = [{"department": d, "year": y, "semester": s, "teacher": t} for d, y, s, t in zip(post.getlist("assignment_departments"),post.getlist("assignment_years"),post.getlist("assignment_semesters"),post.getlist("assignment_teachers"),)]

    try:
        assignments = [{"department": a["department"],"year": int(a["year"]),"semester": int(a["semester"]),"teacher": a["teacher"] or None,} for a in raw_assignments]
    except (TypeError, ValueError):
        messages.error(request, "Invalid year or semester in the department assignments.")
        return render_form(post, raw_assignments, 400)

    data = {"name": post.get("name"),"code": post.get("code"),"subject_type": post.get("subject_type"),"credits": post.get("credits"),"is_active": post.get("is_active"),"college": college_user.college_id, "assignments": assignments,}  # server-side, not from the hidden input

    serializer = SubjectSerializer(data=data)
    if not serializer.is_valid():
        messages.error(request, " | ".join(_flatten_errors(serializer.errors)) or "Please check the entered details and try again.")
        return render_form(post, raw_assignments, 400)

    try:
        with transaction.atomic():
            serializer.save(college=college_user.college)
    except IntegrityError:
        messages.error(request, "A subject with this code already exists in this college.")
        return render_form(post, raw_assignments, 400)
    except Exception:
        logger.exception("Subject creation failed")
        messages.error(request, "Something went wrong while creating the subject. Please try again.")
        return render_form(post, raw_assignments, 500)

    messages.success(request, "Subject created successfully")
    return redirect("college-subjects")


# ---------------------------------------------------------------------------
# Who can edit a subject's core fields / a specific mapping's teacher
# ---------------------------------------------------------------------------
def _staff_profile_for(college_user):
    return StaffProfile.objects.filter(college_user=college_user, is_active=True).select_related("department").first()


def _can_edit_subject(college_user, subject):
    if college_user.role in ("master_admin", "office_admin"):
        return True
    staff_profile = _staff_profile_for(college_user)
    if staff_profile and staff_profile.staff_role == "hod":
        return DepartmentSubjectMapping.objects.filter(subject=subject, department_id=staff_profile.department_id).exists()
    return False


def _can_edit_mapping(college_user, mapping):
    if college_user.role in ("master_admin", "office_admin"):
        return True
    staff_profile = _staff_profile_for(college_user)
    return bool(staff_profile and staff_profile.staff_role == "hod" and staff_profile.department_id == mapping.department_id)


# ---------------------------------------------------------------------------
# Subject detail — core fields + per-department teacher assignments
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subject_detail(request, subject_id):
    college_user = CollegeUser.objects.get(user=request.user)
    subject = get_object_or_404(Subject, id=subject_id, college=college_user.college)

    can_edit_subject = _can_edit_subject(college_user, subject)

    mappings = (DepartmentSubjectMapping.objects.filter(subject=subject).select_related("department", "teacher__college_user__user").order_by("department__name", "year", "semester"))
    mapping_rows = [{"mapping": m, "can_edit": _can_edit_mapping(college_user, m)} for m in mappings]

    staff_members = (StaffProfile.objects.filter(college_user__college=college_user.college, is_active=True).select_related("college_user__user", "department"))

    context = {"subject": subject,"can_edit_subject": can_edit_subject,"mapping_rows": mapping_rows,"staff_members": staff_members,}
    context["year_choices"] = YEAR_CHOICES
    context["semester_choices"] = SEMESTER_CHOICES
    print(context)
    return render(request, "Admin/subject_detail.html", context)


# ---------------------------------------------------------------------------
# Save core subject field edits
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_subject(request, subject_id):
    college_user = CollegeUser.objects.get(user=request.user)
    subject = get_object_or_404(Subject, id=subject_id, college=college_user.college)

    if not _can_edit_subject(college_user, subject):
        return Response({"detail": "You don't have permission to edit this subject."}, status=status.HTTP_403_FORBIDDEN)

    serializer = SubjectUpdateSerializer(subject, data=request.data, partial=True)
    if serializer.is_valid():
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "One or more codes already exist for this college."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Subject updated.", "subject": SubjectUpdateSerializer(subject).data}, status=status.HTTP_200_OK)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Save a single mapping row's teacher (department -> subject assignment)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_subject_mapping_teacher(request, mapping_id):
    college_user = CollegeUser.objects.get(user=request.user)
    mapping = get_object_or_404(DepartmentSubjectMapping.objects.select_related("department", "subject"),id=mapping_id, subject__college=college_user.college,)
    if not _can_edit_mapping(college_user, mapping):
        return Response({"detail": "You don't have permission to edit this assignment."}, status=status.HTTP_403_FORBIDDEN)
    serializer = MappingTeacherUpdateSerializer(mapping, data=request.data, partial=True)
    if serializer.is_valid():
        try:
            serializer.save()
        except IntegrityError:
            return Response({"detail": "This department/year/semester combination already exists."},status=status.HTTP_400_BAD_REQUEST,)
        return Response(
            {"message": "Mapping updated.", "mapping": MappingTeacherUpdateSerializer(mapping).data},status=status.HTTP_200_OK,)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def _apply_filters(queryset, params):
    """Shared filter logic for the HTML list view and the JSON API."""
    department_id = params.get("department")
    academic_year = params.get("academic_year")
    year = params.get("year")
    semester = params.get("semester")
 
    if department_id:
        queryset = queryset.filter(department_id=department_id)
    if academic_year:
        queryset = queryset.filter(academic_year=academic_year)
    if year:
        queryset = queryset.filter(year=year)
    if semester:
        queryset = queryset.filter(semester=semester)
 
    return queryset
 
 
# ---------------------------------------------------------------------------
# Student list — Department -> Academic Year -> Students, with filters +
# a fee-payment-status filter/summary (paid / partial / unpaid / all)
# ---------------------------------------------------------------------------
def _get_student_scope(college_user):
    if college_user.role in ("master_admin", "office_admin"):
        return "all", None
    staff = (StaffProfile.objects.filter(college_user=college_user, is_active=True, department__isnull=False).select_related("department").first())
    if staff:
        return "department", staff.department
    return "none", None

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    scope, scope_department = _get_student_scope(college_user)
    base_qs = StudentProfile.objects.filter(college=college_user.college, is_active=True)
    if scope == "department":
        base_qs = base_qs.filter(department=scope_department)
    elif scope == "none":
        base_qs = base_qs.none()
    qs = _apply_filters(base_qs, request.GET).select_related("college_user", "college_user__user", "department")
    students = list(qs)
    all_departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    if scope == "department":
        all_departments = all_departments.filter(id=scope_department.id)
    elif scope == "none":
        all_departments = all_departments.none()

    departments = all_departments
    department_filter = request.GET.get("department")
    if department_filter:
        departments = departments.filter(id=department_filter)

    students_by_dept = {}
    for stu in students:
        students_by_dept.setdefault(stu.department_id, []).append(stu)

    department_groups = []
    for dept in departments:
        dept_students = _sort_students(students_by_dept.get(dept.id, []))
        year_groups = []
        for academic_year, students_in_year in groupby(dept_students, key=lambda s: s.academic_year or "Unspecified"):
            year_groups.append({"academic_year": academic_year, "students": list(students_in_year)})
        department_groups.append({"department": dept,"year_groups": year_groups,"student_count": len(dept_students),})

    academic_years_qs = StudentProfile.objects.filter(college=college_user.college)
    if scope == "department":
        academic_years_qs = academic_years_qs.filter(department=scope_department)
    elif scope == "none":
        academic_years_qs = academic_years_qs.none()

    context = {"department_groups": department_groups,"departments": all_departments,"academic_years": academic_years_qs.exclude(academic_year="").values_list("academic_year", flat=True).distinct().order_by("-academic_year"),"selected_department": department_filter or "","selected_academic_year": request.GET.get("academic_year", ""),"selected_year": request.GET.get("year", ""),"selected_semester": request.GET.get("semester", ""),"is_department_view": scope == "department",}
    return render(request, "Admin/student_list.html", context)


# JSON variant — same filters, same Department -> Academic Year -> Students shape
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_list_api(request):
    college_user = CollegeUser.objects.get(user=request.user)
    base_qs = StudentProfile.objects.filter(college=college_user.college, is_active=True)
    filtered_qs = _apply_filters(base_qs, request.GET).select_related("college_user", "college_user__user", "department")
 
    departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    department_filter = request.GET.get("department")
    if department_filter:
        departments = departments.filter(id=department_filter)
 
    data = []
    for dept in departments:
        students = filtered_qs.filter(department=dept).order_by("-academic_year", "year", "semester", "roll_number")
        academic_years = []
        for academic_year, students_in_year in groupby(students, key=lambda s: s.academic_year or "Unspecified"):
            academic_years.append({"academic_year": academic_year,"students": StudentListSerializer(list(students_in_year), many=True).data,})
        data.append({"department_id": dept.id,"department_name": dept.name,"academic_years": academic_years,})
 
    return Response(data, status=status.HTTP_200_OK)
 
 
# ---------------------------------------------------------------------------
# Create student — GET renders the form, POST creates the account
# ---------------------------------------------------------------------------
import logging
from django.db import IntegrityError, transaction
logger = logging.getLogger(__name__)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def create_student(request):
    college_user = CollegeUser.objects.get(user=request.user)
    def render_form(form_data=None, status_code=200):
        departments = Department.objects.filter(is_active=True, college=college_user.college)
        return render(request,"Admin/create_student.html",{"departments": departments,"college": college_user.college_id,"form_data": form_data or {},"blood_groups":BLOOD_GROUP_CHOICES},status=status_code,)
    if request.method == "GET":
        return render_form()
    # ---- POST ----
    serializer = StudentCreateSerializer(data=request.data)
    if not serializer.is_valid():
        messages.error(request, _format_serializer_errors(serializer.errors))
        return render_form(request.POST, 400)
    try:
        with transaction.atomic():
            # college is set server-side, never trusted from the client body
            student_profile = serializer.save(college=college_user.college)
            classroom = find_classroom(student_profile)
            if classroom:
                enroll_student(student_profile, classroom)
    except IntegrityError:
        messages.error(request, "A student with this admission number already exists in this college.")
        return render_form(request.POST, 400)
    except Exception:
        logger.exception("Student creation failed")
        messages.error(request, "Something went wrong while creating the student. Please try again.")
        return render_form(request.POST, 500)

    # Student exists from here on, so never re-render the form (it would invite a duplicate submit)
    if not classroom:
        messages.warning(request,"Student created, but no matching classroom exists yet. Create the classroom and enroll them.",)

    user = student_profile.college_user.user
    full_name = f"{user.first_name} {user.last_name}".strip() or user.email
    try:
        student_create_account(student_name=full_name,student_email=user.email,temporary_password=student_profile.generated_password,admission_number=student_profile.admission_number,)
    except Exception:
        logger.exception("Welcome email failed for student %s", student_profile.pk)
        messages.warning(request, "Student created, but the login email could not be sent.")
        return redirect("create-student")

    messages.success(request, "Student created successfully")
    return redirect("create-student")


def _format_serializer_errors(errors):
    parts = []
    for field, msgs in errors.items():
        if isinstance(msgs, (list, tuple)):
            msgs = ", ".join(str(m) for m in msgs)
        parts.append(f"{field}: {msgs}")
    return "; ".join(parts)


def parse_bool(val):
    return str(val).strip().lower() in ("true", "1", "yes", "y")

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def bulk_create_student(request):
    college_user = CollegeUser.objects.filter(user=request.user).first()
    if not college_user or not college_user.college:
        return Response({"error": "Invalid college user association."}, status=status.HTTP_400_BAD_REQUEST)
    college = college_user.college

    def render_page(results=None, show_bulk=False):
        departments = Department.objects.filter(is_active=True, college=college)
        summary = None
        if results is not None:
            ok = sum(1 for r in results if r["status"] == "success")
            summary = {"total": len(results), "success": ok, "failed": len(results) - ok}
        return render(request, "Admin/create_student.html", {"departments": departments,"college": college.id,"bulk_results": results,"bulk_summary": summary,"show_bulk": show_bulk,})

    if request.method == "GET":
        return render_page()

    # ---------- POST: Excel bulk upload ----------
    file = request.FILES.get("file")
    if not file:
        messages.error(request, "An Excel file (.xlsx) is required.")
        return render_page(show_bulk=True)

    try:
        # dtype=str stops pandas turning "1001" into "1001.0" and year "2" into 2.0
        df = pd.read_excel(file, dtype=str)
        df = df.fillna("")
    except Exception as e:
        messages.error(request, f"Failed to parse Excel file: {e}")
        return render_page(show_bulk=True)

    results = []

    def add_result(row_num, email, admission_number, ok, message):
        results.append({"row": row_num,"email": email,"admission_number": admission_number,"status": "success" if ok else "failed","message": message,})

    departments = {d.name.lower(): d for d in Department.objects.filter(college=college, is_active=True)}
    valid_statuses = {"active", "graduated", "dropped_out", "transferred", "suspended"}  # keep in sync with model choices
    chars = string.ascii_letters + string.digits + "!@#$%^&*"

    for index, row in df.iterrows():
        row_num = index + 2
        get = lambda k: str(row.get(k, "")).strip()

        email = get("email")
        first_name = get("first_name")
        last_name = get("last_name")
        dept_name = get("department").lower()
        admission_number = get("admission_number")

        def fail(msg):
            add_result(row_num, email, admission_number, False, msg)

        if not email:
            fail("Email is required."); continue
        if not admission_number:
            fail("Admission Number is required."); continue

        department = departments.get(dept_name)
        if dept_name and not department:
            fail(f"Department '{get('department')}' not found in this college."); continue

        qualifying_marks = None
        if get("qualifying_marks_percentage"):
            try:
                qualifying_marks = float(get("qualifying_marks_percentage"))
            except ValueError:
                fail("qualifying_marks_percentage must be a number."); continue
            if not (0 <= qualifying_marks <= 100):
                fail("qualifying_marks_percentage must be between 0 and 100."); continue

        row_status = get("status").lower() or "active"
        if row_status not in valid_statuses:
            fail(f"status '{row_status}' is invalid. Choose from {sorted(valid_statuses)}."); continue

        graduation_date = get("graduation_date") or None
        if row_status == "graduated" and not graduation_date:
            fail("graduation_date is required when status is 'graduated'."); continue

        def to_int(key):
            v = get(key)
            try:
                return int(float(v)) if v else None
            except ValueError:
                return None

        generated_password = get_random_string(length=10, allowed_chars=chars)
        data = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "mobile_number": get("mobile_number") or None,
            "password": generated_password,
            "admission_number": admission_number,
            "roll_number": get("roll_number") or None,
            "department": department.id if department else None,
            "academic_year": get("academic_year") or None,
            "year": to_int("year"),
            "semester": to_int("semester"),
            "section": get("section") or None,
            "blood_group": get("blood_group") or None,
            "emergency_contact_number": get("emergency_contact_number") or None,
            "address": get("address") or None,
            "date_of_birth": get("date_of_birth") or None,
            "qualifying_marks_percentage": qualifying_marks,
            "is_first_generation_graduate": parse_bool(get("is_first_generation_graduate")),
            "status": row_status,
            "graduation_date": graduation_date,
            "is_hostellar": parse_bool(get("is_hostellar")),
        }

        serializer = StudentCreateSerializer(data=data)
        if not serializer.is_valid():
            fail(_format_serializer_errors(serializer.errors)); continue
        try:
            with transaction.atomic():
                serializer.save(college=college)
                full_name = f"{first_name} {last_name}".strip() or email
                student_create_account(student_name=full_name,student_email=email,temporary_password=generated_password,admission_number=admission_number,)
            add_result(row_num, email, admission_number, True, "Student created and email sent.")
        except IntegrityError:
            fail(f"Student with admission number '{admission_number}' or email already exists.")
        except Exception as e:
            fail(f"Unexpected error: {e}")
    return render_page(results=results, show_bulk=True)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download_student_sample(request):
    columns = ["first_name","last_name","email","mobile_number","admission_number","roll_number","department","academic_year","year","semester","section","date_of_birth","blood_group","emergency_contact_number","address","qualifying_marks_percentage", "is_first_generation_graduate","status", "graduation_date", "is_hostellar",]
    sample_data = [{"first_name": "John","last_name": "Doe","email": "sample@example.com","mobile_number": "+910123456789","admission_number": "ADM-2024-001","roll_number": "24CS001","department": "Computer Science","academic_year": "2024-2028","year": 1,"semester": 1,"section": "A","date_of_birth": "2005-01-01","blood_group": "O+","emergency_contact_number": "+910123456789","address": "45 ABC Road, City","qualifying_marks_percentage": 92.5, "is_first_generation_graduate": "TRUE","status": "active", "graduation_date": "", "is_hostellar": "FALSE",}]
    df = pd.DataFrame(sample_data, columns=columns)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Student Upload Template")
    output.seek(0)
    response = HttpResponse(output.getvalue(),content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",)
    response["Content-Disposition"] = 'attachment; filename="student_upload_sample.xlsx"'
    return response

import calendar as cal_module

# ---------------------------------------------------------------------------
# Student detail — profile + a month calendar colored by attendance status
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_detail(request, student_id):
    college_user = CollegeUser.objects.get(user=request.user)
    student = get_object_or_404(StudentProfile.objects.select_related("college_user__user", "department"),id=student_id, college=college_user.college,)

    today = date.today()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    _, days_in_month = cal_module.monthrange(year, month)
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    records = (StudentAttendance.objects.filter(student=student, session__date__range=(month_start, month_end)).select_related("session"))
    day_statuses = {}  # date -> set of status codes recorded that day
    for r in records:
        day_statuses.setdefault(r.session.date, set()).add(r.status)

    # A day can have several periods with different statuses — pick one
    # headline color. Absent takes priority (flags the day even if the
    # student was present elsewhere), then Late, then On Duty, then Present.
    def summarize(statuses):
        if "A" in statuses:
            return "A"
        if "L" in statuses:
            return "L"
        if "OD" in statuses:
            return "OD"
        if "P" in statuses:
            return "P"
        return None

    calendar_grid = cal_module.Calendar(firstweekday=6)  # weeks start Sunday
    weeks = []
    for week in calendar_grid.monthdatescalendar(year, month):
        week_cells = []
        for d in week:
            in_month = d.month == month
            statuses = day_statuses.get(d, set()) if in_month else set()
            week_cells.append({"date": d,"in_month": in_month,"is_today": d == today,"is_future": d > today,"is_sunday": d.weekday() == 6,"status": summarize(statuses),})
        weeks.append(week_cells)

    summary_counts = {code: 0 for code, _ in StudentAttendance.STATUS_CHOICES}
    for statuses in day_statuses.values():
        headline = summarize(statuses)
        if headline:
            summary_counts[headline] += 1

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)
    next_is_future = date(next_year, next_month, 1) > today
    
    departments = Department.objects.filter(is_active=True, college=college_user.college)
    context = {"departments":departments,"student": student,"year": year,"month": month,"month_label": month_start.strftime("%B %Y"),"weeks": weeks,"prev_year": prev_year, "prev_month": prev_month,"next_year": next_year, "next_month": next_month,"next_disabled": next_is_future,"summary_counts": summary_counts,  }
    return render(request, "Admin/student_details.html", context)


# ---------------------------------------------------------------------------
# Save edits to a student's profile fields
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_student_profile(request, student_id):
    college_user = CollegeUser.objects.get(user=request.user)
    student = get_object_or_404(StudentProfile.objects.select_related("college_user__user"),id=student_id, college=college_user.college,)
    serializer = StudentProfileUpdateSerializer(student, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    send_pw = serializer.validated_data.get("send_password", False)
    password_sent = False
    try:
        with transaction.atomic():
            serializer.save()
            student.refresh_from_db()
            user = student.college_user.user
            if send_pw:
                new_password = _generate_password()
                user.set_password(new_password)
                user.save(update_fields=["password"])
                student_create_account(student_name=user.first_name,student_email=user.email,temporary_password=new_password,admission_number=student.admission_number,)
                
                password_sent = True
    except IntegrityError:
        return Response({"detail": "Email, mobile number or admission number already in use."},status=status.HTTP_400_BAD_REQUEST)
    except (smtplib.SMTPException, OSError):
        return Response({"detail": "Could not send the email, so no changes were saved. Check the email address and try again."},status=status.HTTP_502_BAD_GATEWAY)
    return Response({"message": "Student profile updated.","password_sent": password_sent,"student": StudentDetailSerializer(student).data,}, status=status.HTTP_200_OK)

# ---------------------------------------------------------------------------
# Classroom list — Department -> Year -> Sections
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def classroom_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access = get_classroom_access(college_user)
    print("access",access)
    if access["level"] == "none":
        raise PermissionDenied("You do not have access to classrooms.")
    ay = _resolve_academic_year(request, college)
    if ay is None and access["level"] == "full":
        return redirect("create-classroom")
    
    department_groups = []
   
    department_groups = []
    if ay is not None:
        print(ay)
        classrooms_qs = scope_classrooms(Classroom.objects.filter(college=college, academic_year=ay),access, request.user,).select_related("department").order_by("year", "semester", "section")
        print(classrooms_qs)
        by_dept = defaultdict(list)
        for c in classrooms_qs:
            by_dept[c.department_id].append(c)

        for dept in visible_departments(college, access, classrooms_qs):
            classrooms = by_dept.get(dept.id, [])
            year_groups = []
            for year, group in groupby(classrooms, key=lambda c: c.year):
                group = list(group)
                year_groups.append({"year": year,"year_display": group[0].get_year_display(),"classrooms": group,})
            department_groups.append({"department": dept,"year_groups": year_groups,"classroom_count": len(classrooms),})
 
    context = {"department_groups": department_groups,"academic_years": AcademicYear.objects.filter(college=college),"selected_academic_year": ay,"can_create_classroom": access["can_create"],"access_level": access["level"],}
    return render(request, "Admin/classroom_list.html", context)


 
# ---------------------------------------------------------------------------
# Classroom detail page
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def classroom_detail(request, classroom_id):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access, classroom = _get_scoped_classroom(request, college_user, classroom_id)
 
    can_manage = _can_manage_classroom(access, classroom)
    can_assign = can_manage and classroom.is_active
 
    # ---- Students (active enrollments in this classroom) ----
    enrollments = list(StudentEnrollment.objects.filter(classroom=classroom, is_active=True).select_related("student__college_user__user").order_by("roll_number", "student__admission_number"))
    student_rows = [{"name": _display_name(e.student.college_user.user),"admission_number": e.student.admission_number,"roll_number": e.roll_number or e.student.roll_number,"status": e.get_status_display(),"is_hostellar": e.student.is_hostellar,} for e in enrollments]
 
    # ---- Subjects mapped to this department / year / semester ----
    mappings = (DepartmentSubjectMapping.objects.filter(department=classroom.department,year=classroom.year,semester=classroom.semester,subject__college=college,).select_related("subject", "teacher__college_user__user", "teacher__department").order_by("subject__name"))
    subject_rows = list(mappings)
    print(subject_rows)
 
    # ---- Staff list: advisor + HOD + everyone teaching a subject here ----
    advisor = (StaffProfile.objects.filter(department=classroom.department, staff_role="class_advisor",advisor_year=classroom.year, is_active=True,).select_related("college_user__user").first())
    hod = (StaffProfile.objects.filter(department=classroom.department, staff_role="hod", is_active=True,).select_related("college_user__user").first())
    taught = defaultdict(list)
    teacher_obj = {}
    
    for m in subject_rows:
        print(m.teacher_id)
        if m.teacher_id:
            subject_name = (m.subject.short_name if m.subject.short_name and m.subject.short_name != "--" else m.subject.name)
            taught[m.teacher_id].append(subject_name)
            teacher_obj[m.teacher_id] = m.teacher
            print(m.teacher)
            
            print(taught)
            
 
    staff_rows = []
    if advisor:
        staff_rows.append({"name": _display_name(advisor.college_user.user),"role": "Class Advisor", "subjects": taught.pop(advisor.id, [])})
    if hod and (not advisor or hod.id != advisor.id):
        staff_rows.append({"name": _display_name(hod.college_user.user),"role": "HOD", "subjects": taught.pop(hod.id, [])})
    for tid, subs in taught.items():
        staff_rows.append({"name": _display_name(teacher_obj[tid].college_user.user),"role": "Subject Teacher", "subjects": subs})
 
    staff_members = (StaffProfile.objects.filter(college_user__college=college, is_active=True).select_related("college_user__user", "department").order_by("college_user__user__first_name"))
 
    # ---- Fee summary: visible ONLY to this classroom's class advisor ----
    is_advisor = _is_class_advisor(college_user, classroom)
    fee_summary = _build_fee_summary(classroom, enrollments) if is_advisor else None
 
    context = {"classroom": classroom,"can_manage": can_manage,"can_assign": can_assign,"timetable": _build_timetable(classroom),"student_rows": student_rows,"student_count": len(student_rows),"staff_count": len(staff_rows),"attendance_today": _today_attendance(classroom, enrollments),"staff_rows": staff_rows,"subject_rows": subject_rows,"staff_members": staff_members,"is_advisor": is_advisor,"fee_summary": fee_summary,}
    return render(request, "Admin/classroom_detail.html", context)
 
 
# ---------------------------------------------------------------------------
# Save classroom details (name, section, room, active)
# Year / semester are intentionally NOT editable: enrollments copy them from
# the classroom at save time, so changing them would desync student records.
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def update_classroom(request, classroom_id):
    college_user = CollegeUser.objects.get(user=request.user)
    access, classroom = _get_scoped_classroom(request, college_user, classroom_id)
 
    if not _can_manage_classroom(access, classroom):
        return Response({"detail": "You don't have permission to edit this classroom."},status=status.HTTP_403_FORBIDDEN)
 
    name = (request.data.get("name") or "").strip()
    if not name:
        return Response({"detail": "Classroom name is required."}, status=status.HTTP_400_BAD_REQUEST)
 
    classroom.name = name
    classroom.section = (request.data.get("section") or "").strip()
    classroom.room_number = (request.data.get("room_number") or "").strip() or None
 
    is_active = bool(request.data.get("is_active", classroom.is_active))
    if is_active != classroom.is_active:
        classroom.is_active = is_active
        classroom.closed_on = None if is_active else timezone.localdate()
 
    try:
        classroom.save()
    except IntegrityError:
        return Response({"detail": "A classroom with this department, year, semester and section already exists."},status=status.HTTP_400_BAD_REQUEST,)
    return Response({"message": "Classroom updated.","classroom": {"name": classroom.name, "section": classroom.section,"room_number": classroom.room_number or "", "is_active": classroom.is_active,},}, status=status.HTTP_200_OK)
 
 
# ---------------------------------------------------------------------------
# Assign / de-assign the teacher of one subject
# teacher = <StaffProfile id>  -> assign
# teacher = null               -> de-assign
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_classroom_subject_teacher(request, classroom_id, mapping_id):
    college_user = CollegeUser.objects.get(user=request.user)
    access, classroom = _get_scoped_classroom(request, college_user, classroom_id)
 
    if not (_can_manage_classroom(access, classroom) and classroom.is_active):
        return Response({"detail": "You can't change assignments for this classroom."},status=status.HTTP_403_FORBIDDEN)
 
    mapping = get_object_or_404(DepartmentSubjectMapping,id=mapping_id,department=classroom.department,year=classroom.year,semester=classroom.semester,subject__college=college_user.college,)
 
    teacher = None
    teacher_id = request.data.get("teacher") or None
    if teacher_id:
        try:
            teacher = StaffProfile.objects.select_related("college_user__user").filter(id=teacher_id, college_user__college=college_user.college, is_active=True,).first()
        except (ValueError, ValidationError):
            teacher = None
        if teacher is None:
            return Response({"detail": "Selected staff member was not found."},
                            status=status.HTTP_400_BAD_REQUEST)
 
    with transaction.atomic():
        mapping.teacher = teacher
        mapping.save(update_fields=["teacher"])
        # Keep this classroom's timetable periods for the subject in sync.
        TimetableSlot.objects.filter(classroom=classroom, subject_mapping=mapping).update(teacher=teacher.college_user.user if teacher else None)
 
    return Response({"message": "Teacher assigned." if teacher else "Teacher removed.","teacher_id": str(teacher.id) if teacher else "","teacher_name": _display_name(teacher.college_user.user) if teacher else "",}, status=status.HTTP_200_OK)
 
 
# ---------------------------------------------------------------------------
# Create classroom — GET renders the form, POST creates it
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enrollment_candidates(request):
    college_user = _get_college_user(request)
    access = get_classroom_access(college_user)
    if not access["can_create"]:
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
 
    dept, year, sem = (request.GET.get(k) for k in ("department", "year", "semester"))
    if not (dept and year and sem):
        return Response({"students": []})
    dept_uuid = valid_uuid(dept)
    allowed = creatable_departments(college_user.college, access)
    if not dept_uuid or not allowed.filter(id=dept_uuid).exists():
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
 
    students = (StudentProfile.objects.filter(college=college_user.college, is_active=True, status="active",department_id=dept_uuid, year=year, semester=sem).select_related("college_user__user").order_by("roll_number", "admission_number"))
 
    elsewhere = {}
    ay_id = request.GET.get("academic_year")
    if ay_id and ay_id != "__new__" and valid_uuid(ay_id):
        elsewhere = dict(StudentEnrollment.objects.filter(academic_year_id=ay_id, semester=sem, status="active",classroom__college=college_user.college,).values_list("student_id", "classroom__section"))
 
    rows = []
    for s in students:
        u = s.college_user.user
        rows.append({"id": str(s.id),"name": f"{u.first_name} {u.last_name}".strip() or u.email,"admission_number": s.admission_number,"roll_number": s.roll_number,"enrolled_section": elsewhere.get(s.id),"is_enrolled": s.id in elsewhere,})
    return Response({"students": rows})

@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def create_classroom(request):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access = get_classroom_access(college_user)
    if not access["can_create"]:
        raise PermissionDenied("You do not have permission to create classrooms.")
    departments = creatable_departments(college, access)

    if request.method == "GET":
        academic_years = AcademicYear.objects.filter(college=college)
        if not academic_years.exists() and not access["can_manage_academic_years"]:
            return redirect("college-classrooms")
        context = {"departments": departments,"academic_years": academic_years,"current_academic_year": academic_years.filter(is_current=True).first(),"can_manage_academic_years": access["can_manage_academic_years"],}
        return render(request, "Admin/create_classroom.html", context)

    data = request.data
    dept_id = valid_uuid(data.get("department"))
    if not dept_id or not departments.filter(id=dept_id).exists():
        return Response({"department": ["You can only create classrooms for your own department."]},status=status.HTTP_403_FORBIDDEN,)

    # 2) only master/office admin may create or switch academic years
    if data.get("new_academic_year") and not access["can_manage_academic_years"]:
        return Response({"academic_year": ["Only master admin or office admin can create an academic year."]},status=status.HTTP_403_FORBIDDEN,)

    # 3) students being enrolled must belong to that department and college
    student_ids = data.get("student_ids") or []
    if not isinstance(student_ids, list):                       # change 1: guard bad input
        return Response({"student_ids": ["Invalid student selection."]}, status=status.HTTP_400_BAD_REQUEST)
    if student_ids:
        try:
            in_college = StudentProfile.objects.filter(id__in=student_ids, college=college)
            foreign = in_college.exclude(department_id=dept_id).exists()
            found = in_college.count()
        except (ValidationError, ValueError):
            return Response({"student_ids": ["Invalid student selection."]}, status=status.HTTP_400_BAD_REQUEST)
        if foreign or found != len(set(map(str, student_ids))):
            return Response({"student_ids": ["Students must belong to this classroom's department."]},status=status.HTTP_400_BAD_REQUEST,)

    serializer = ClassroomCreateSerializer(data=data, context={"college": college})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    try:
        with transaction.atomic():                              # change 2: all-or-nothing
            classroom = serializer.save(college=college)
    except IntegrityError:
        return Response({"section": ["A classroom with this department, year, semester and section already exists."]},status=status.HTTP_400_BAD_REQUEST,)

    return Response(ClassroomListSerializer(classroom).data, status=status.HTTP_201_CREATED)

import datetime
DAYS_OF_WEEK = [(1, "Monday"), (2, "Tuesday"), (3, "Wednesday"), (4, "Thursday"), (5, "Friday"), (6, "Saturday")]
DEFAULT_PERIOD_LENGTH_MINUTES = 50
DEFAULT_FIRST_PERIOD_START = time(9, 0)
def _default_period_time(period_number):
    """Falls back to a sensible 50-min slot starting at 9:00 when no time is saved yet."""
    start_minutes = (period_number - 1) * DEFAULT_PERIOD_LENGTH_MINUTES
    today = datetime.date.today()
    start = (datetime.datetime.combine(today, DEFAULT_FIRST_PERIOD_START)
             + datetime.timedelta(minutes=start_minutes)).time()
    end = (datetime.datetime.combine(today, start)
           + datetime.timedelta(minutes=DEFAULT_PERIOD_LENGTH_MINUTES)).time()
    return start, end
 
# ---------------------------------------------------------------------------
# Weekly timetable grid for one classroom — Day (columns) x Period (rows)
# ---------------------------------------------------------------------------

def _classroom_order():
    return ("department__name", "year", "semester", "section")

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def timetable(request):
    college_user = get_object_or_404(CollegeUser, user=request.user)
    college = college_user.college
    access = get_schedule_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have access to timetables.")
    classroom, ay = _get_classroom_and_year(request, college)
    if ay is None:
        return redirect("create-classroom")

    # Filter classrooms by college AND the selected academic year (ay)
    if ay is None:
        classrooms = Classroom.objects.none()
    else:
        classrooms = scope_schedule_classrooms(Classroom.objects.filter(college=college, academic_year=ay), access, request.user)
        classrooms = Classroom.objects.filter(id__in=classrooms.values("id")) \
            .select_related("department").order_by(*_classroom_order())
    
    if classroom and not classrooms.filter(id=classroom.id).exists():
        raise PermissionDenied("You do not have access to this classroom's timetable.")
 
    periods, rows = [], []
    if classroom:
        slots = (TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject","subject_mapping__teacher__college_user__user","teacher",).order_by("period_number", "day_of_week"))

        # 1. Gather distinct period timings
        period_meta, all_period_numbers = {}, set()

        for s in slots:
            all_period_numbers.add(s.period_number)
            if s.start_time and s.end_time:
                period_meta.setdefault(
                    s.period_number,{"period_number": s.period_number,"start_time": s.start_time.strftime("%H:%M"),"end_time": s.end_time.strftime("%H:%M"),},)

        for p in (sorted(all_period_numbers) if all_period_numbers else list(range(1, 7))):
            periods.append(period_meta.get(p, {"period_number": p, "start_time": "", "end_time": ""}))

        # 2. Build fast lookup map for cells: (day_value, period_number) -> cell_dict
        slot_map = {}
        for s in slots:
            staff_name, staff_designation = "", ""

            if s.subject_mapping and s.subject_mapping.teacher:
                staff_name, staff_designation = _staff_display(s.subject_mapping.teacher)

            if not staff_name and s.teacher:
                staff_name = s.teacher.get_full_name() or s.teacher.username

            subject = s.subject_mapping.subject if s.subject_mapping else None
            slot_map[(s.day_of_week, s.period_number)] = {"slot_id": str(s.id),"subject_code": subject.code if subject else "","subject_short_name": subject.short_name if subject else "","subject_name": subject.name if subject else "No Subject","staff_name": staff_name or "N/A","staff_designation": staff_designation,}

        # 3. Construct rows grouped by Day
        for day_value, day_label in DAYS_OF_WEEK:
            cells = [{"period_number": p["period_number"],"data": slot_map.get((day_value, p["period_number"]))} for p in periods]
            rows.append({"day_value": day_value, "day_label": day_label, "cells": cells})
    can_edit = bool(classroom) and can_edit_timetable_for(access, classroom)
    is_read_only = (not can_edit) or (ay is None or not ay.is_current) or (bool(classroom) and not classroom.is_active)
 
    context = {"classrooms": classrooms,"classroom": classroom,"days": DAYS_OF_WEEK,"periods": periods,"rows": rows,"academic_years": AcademicYear.objects.filter(college=college),"selected_academic_year": ay,"is_read_only": is_read_only,"can_edit_timetable": can_edit,}
    return render(request, "Admin/timetable_list.html", context)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def create_timetable_slot(request):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access = get_schedule_access(college_user)
    classroom, ay = _get_classroom_and_year(request, college)

    # Filter classrooms by college AND the selected academic year
    classrooms = editable_timetable_classrooms(Classroom.objects.filter(college=college, academic_year=ay), access).select_related("department").order_by(*_classroom_order())
    if access["level"] == "none" or not (access["level"] == "full" or access["role"] == "hod"):
        raise PermissionDenied("You do not have permission to edit timetables.")
    if classroom is None:
        classroom = classrooms.first()
    elif not classrooms.filter(id=classroom.id).exists():
        raise PermissionDenied("You can only edit timetables of your own department.")

    try:
        period_count = max(1, min(int(request.GET.get("period_count", 8)), 12))
    except ValueError:
        period_count = 8
    rows, subject_mappings, period_columns = [], [], []
 

    if classroom:
        # Subjects scoped to this classroom's department AND its exact year/semester
        subject_mappings = DepartmentSubjectMapping.objects.filter(department=classroom.department, year=classroom.year, semester=classroom.semester,).select_related("subject")

        # Pull every slot for this classroom
        existing_slots = TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject")
        slot_by_day_period = {(s.day_of_week, s.period_number): s for s in existing_slots}

        period_time_defaults = {}
        for s in existing_slots:
            period_time_defaults.setdefault(s.period_number, (s.start_time, s.end_time))

        for day_value, day_label in DAYS_OF_WEEK:
            cells = [{"period_number": n, "slot": slot_by_day_period.get((day_value, n))}
                     for n in range(1, period_count + 1)]
            rows.append({"day_value": day_value, "day_label": day_label, "cells": cells})

        for n in range(1, period_count + 1):
            start, end = period_time_defaults.get(n, _default_period_time(n))
            period_columns.append({"period_number": n, "start_time": start, "end_time": end})

    context = {"classrooms": classrooms,"classroom": classroom,"period_count": period_count,"rows": rows,"period_columns": period_columns,"subject_mappings": subject_mappings,"academic_years": AcademicYear.objects.filter(college=college),"selected_academic_year": ay,"is_read_only": (not ay.is_current) or (bool(classroom) and not classroom.is_active),}
    return render(request, "Admin/create_timetable_slot.html", context)



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_timetable_grid(request):
    college_user = _get_college_user(request)
    access = get_schedule_access(college_user)
    classroom_id = valid_uuid(request.data.get("classroom"))
    if not classroom_id:
        return Response({"classroom": "Classroom is required."}, status=status.HTTP_400_BAD_REQUEST)
 
    classroom = get_object_or_404(Classroom, id=classroom_id, college=college_user.college)
    if not can_edit_timetable_for(access, classroom):
        raise PermissionDenied("You do not have permission to edit this timetable.")
    if not classroom.is_active or (classroom.academic_year and not classroom.academic_year.is_current):
        raise PermissionDenied("This classroom's timetable is read-only.")
 
    serializer = TimetableGridSaveSerializer(data=request.data, context={"college": college_user.college})
    if serializer.is_valid():
        created = serializer.save()
        return Response({"message": "Timetable saved.","slots_created": len(created),},status=status.HTTP_200_OK,)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------------
# Attendance — Step 1: pick Department -> Year -> Section (for one academic year)
# ---------------------------------------------------------------------------
def _render_attendance_select(request, college_user):
    college = college_user.college
    access = get_schedule_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have access to attendance.")
    ay = _resolve_academic_year(request, college)
 
    if ay is None:
        classrooms = []
    else:
        visible = scope_schedule_classrooms(Classroom.objects.filter(college=college, academic_year=ay), access, request.user)
        # Filter by id__in so the scope's joins can't inflate the student counts
        classrooms = list(Classroom.objects.filter(id__in=visible.values("id")).annotate(student_count=Count("enrollments", filter=Q(enrollments__status="active") | Q(is_active=False))).order_by("year", "semester", "section"))
    by_dept = defaultdict(list)
    for c in classrooms:
        by_dept[c.department_id].append(c)
 
    departments = Department.objects.filter(is_active=True, college=college).order_by("name")
    if access["level"] != "full":
        departments = departments.filter(id__in=by_dept.keys())   # includes other departments you teach in
    department_groups = []
    for dept in departments:
        classrooms = by_dept.get(dept.id, [])
        year_groups = []
        for year, group in groupby(classrooms, key=lambda c: c.year):
            rows = [{"classroom": c, "student_count": c.student_count} for c in group]
            year_groups.append({"year": year, "year_display": rows[0]["classroom"].get_year_display(), "rows": rows})
        department_groups.append({"department": dept, "year_groups": year_groups, "classroom_count": len(classrooms)})
 
    context = {
        "department_groups": department_groups,
        "academic_years": AcademicYear.objects.filter(college=college),
        "selected_academic_year": ay,"can_enroll_students": access["can_enroll"],
        "access_level": access["level"],
    }
    return render(request, "Admin/attendance_select.html", context)
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_select(request):
    return _render_attendance_select(request, _get_college_user(request))
 


# ---------------------------------------------------------------------------
# Who can edit which periods for a given classroom/day
# ---------------------------------------------------------------------------
def _get_editable_slot_ids(request_user, college_user, classroom, weekday, all_slots):
    return editable_attendance_slot_ids(request_user, college_user, classroom, all_slots)
    if not classroom.is_active:
        return set()
    all_ids = {s.id for s in all_slots}

    if college_user.role in ("master_admin", "office_admin"):
        return all_ids

    staff_profile = StaffProfile.objects.filter(college_user=college_user, is_active=True).select_related("department").first()
    if not staff_profile:
        return set()

    if staff_profile.staff_role == "hod" and staff_profile.department_id == classroom.department_id:
        return all_ids

    if staff_profile.staff_role == "class_advisor":
        # TODO: replace with your real Classroom -> advisor relation once it
        # exists (e.g. classroom.class_advisor_id == staff_profile.id).
        # Left as full-access for now so advisors aren't blocked.
        return all_ids

    # Plain subject teacher — only the periods they actually teach today
    return {s.id for s in all_slots if s.teacher_id == request_user.id}


# ---------------------------------------------------------------------------
# Step 2 — take attendance: week strip + full day matrix (students x periods)
# ---------------------------------------------------------------------------

def classroom_enrollments(classroom, only_active=None):
    qs = StudentEnrollment.objects.filter(classroom=classroom,year=classroom.year,semester=classroom.semester,)
    if classroom.academic_year_id:                      # academic_year is nullable on Classroom
        qs = qs.filter(academic_year_id=classroom.academic_year_id)
    if only_active is None:
        only_active = classroom.is_active
    if only_active:
        qs = qs.filter(status="active", is_active=True)
    return qs


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def take_attendance(request):
    college_user = _get_college_user(request)
    if not request.GET.get("classroom"):
        return _render_attendance_select(request, college_user)
    access = get_schedule_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have access to attendance.")
    
    classroom, ay = _get_classroom_and_year(request, college_user.college)
    visible = scope_schedule_classrooms(Classroom.objects.filter(college=college_user.college), access, request.user)
    if not visible.filter(id=classroom.id).exists():
        raise PermissionDenied("You do not have access to this classroom.")

    # ---- Date handling ----
    today = date.today()
    date_str = request.GET.get("date")
    try:
        selected_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else today
    except ValueError:
        return HttpResponseBadRequest("Invalid date. Use YYYY-MM-DD.")

    is_future = selected_date > today
    weekday = selected_date.weekday() + 1  # Python Mon=0 -> model Mon=1 ... Sat=6
    is_sunday = weekday == 7
    out_of_range = not (ay.start_date <= selected_date <= ay.end_date)
    is_locked = not ay.is_current

    # ---- Week strip: Sunday -> Saturday containing selected_date ----
    py_weekday = selected_date.weekday()  # Mon=0 .. Sun=6
    days_since_sunday = (py_weekday + 1) % 7
    week_start = selected_date - datetime.timedelta(days=days_since_sunday)
    week_dates = []
    for i in range(7):
        d = week_start + datetime.timedelta(days=i)
        week_dates.append({"date": d,"is_selected": d == selected_date,"is_future": d > today,"is_today": d == today,})

    # ---- Periods scheduled for this classroom on this weekday ----
    if is_sunday or out_of_range:
        periods_list = []
    else:
        periods_list = list(TimetableSlot.objects.filter(classroom=classroom,academic_year=classroom.academic_year, day_of_week=weekday).select_related("subject_mapping__subject", "teacher").order_by("period_number"))
    

    editable_ids = set() if (is_future or is_locked) else _get_editable_slot_ids(request.user, college_user, classroom, weekday, periods_list)

    now_time = datetime.datetime.now().time()
    current_period_id = None
    if selected_date == today:
        for p in periods_list:
            if p.start_time <= now_time <= p.end_time:
                current_period_id = p.id
                break

    periods = [{"slot": p,"editable": p.id in editable_ids,} for p in periods_list]
    
    # closed class: every enrollment ever made in it, so last term's students and records stay visible
    enrollments = list(classroom_enrollments(classroom).select_related("student__college_user__user").order_by("roll_number"))
    print("not is_active classroom")
    status_map = {}  # {(slot_id, student_id): status}
    if periods_list:
        rows_qs = StudentAttendance.objects.filter(session__timetable_slot__in=periods_list, session__date=selected_date,).values_list("session__timetable_slot_id", "student_id", "status")
        for slot_id, student_id, st in rows_qs:
            status_map[(slot_id, student_id)] = st
    # ---- Roster + existing statuses across every period for this date ----
    roster_matrix = []
    present_students, absent_students = set(), set()
    for en in enrollments:
        student = en.student
        cells = []
        for p in periods_list:
            st = status_map.get((p.id, student.id))
            cells.append({"period_id": p.id, "status": st or ""})
            if st == "P":
                present_students.add(student.id)
            elif st == "A":
                absent_students.add(student.id)
        roster_matrix.append({"student": student, "roll_number": en.roll_number, "cells": cells})
 

    student_count = len(enrollments)
    current_present = sum(
        1 for row in roster_matrix
        for c in row["cells"] if c["period_id"] == current_period_id and c["status"] == "P"
    ) if current_period_id else 0

    def pct(n):
        return round((n / student_count) * 100) if student_count else 0
    periods
    stats = {"student_count": student_count,"today_present": len(present_students),"today_present_pct": pct(len(present_students)),"today_absent": len(absent_students),"today_absent_pct": pct(len(absent_students)),"current_period_count": current_present,"current_period_pct": pct(current_present),}
    context = {"classroom": classroom,"selected_academic_year": ay,"academic_years": AcademicYear.objects.filter(college=college_user.college),"selected_date": selected_date,"week_dates": week_dates,"is_sunday": is_sunday,"is_future": is_future,"is_locked": is_locked,"periods": periods, "out_of_range": out_of_range,"roster_matrix": roster_matrix,"status_choices": StudentAttendance.STATUS_CHOICES,"stats": stats,"any_editable": any(p["editable"] for p in periods),}
    print(context)
    return render(request, "Admin/take_attendance.html", context)

# ---------------------------------------------------------------------------
# Bulk save — persists the final per-student statuses for one period/date
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def save_attendance(request):
    college_user = _get_college_user(request)
    print("inside save attendance")
    print(request.data)
    serializer = SaveAttendanceMatrixSerializer(data=request.data, context={"college": college_user.college})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Recompute editable slots server-side — never trust the client's list
    entries = serializer.validated_data["entries"]
    weekday = serializer.validated_data["date"].weekday() + 1
    editable_ids = set()
    if not entries:
        return Response({"non_field_errors": ["No periods submitted."]}, status=status.HTTP_400_BAD_REQUEST)
    for classroom in {e["timetable_slot"].classroom for e in entries}:
        all_slots = list(TimetableSlot.objects.filter(classroom=classroom, day_of_week=weekday))
        editable_ids |= _get_editable_slot_ids(request.user, college_user, classroom, weekday, all_slots)
 
    # PermissionDenied raised inside save() becomes a 403 automatically
    sessions = serializer.save(taken_by=request.user, editable_slot_ids=editable_ids)

    return Response({"message": "Attendance saved.","sessions_saved": len(sessions),"students_recorded": sum(len(e["records"]) for e in entries),}, status=status.HTTP_200_OK)
    
# ---------------------------------------------------------------------------
# Student attendance history — any academic year / semester
# GET /students/<id>/attendance/?academic_year=<uuid>&semester=1
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_attendance_history(request, student_id):
    college_user = _get_college_user(request)
    student = _get_object_or_404_uuid(StudentProfile, id=student_id, college=college_user.college)
 
    # Students may only view their own record (adjust the role value to yours)
    if college_user.role == "student" and student.college_user_id != college_user.id:
        return Response({"detail": "Not allowed."}, status=status.HTTP_403_FORBIDDEN)
 
    qs = StudentAttendance.objects.filter(student=student)
 
    ay_id = request.GET.get("academic_year")
    if ay_id:
        ay = _get_object_or_404_uuid(AcademicYear.objects.filter(college=college_user.college), id=ay_id)
        qs = qs.filter(session__academic_year=ay)
 
    semester = request.GET.get("semester")
    if semester:
        qs = qs.filter(session__timetable_slot__classroom__semester=semester)
 
    summary = (
        qs.values(
            academic_year=F("session__academic_year__name"),
            semester=F("session__timetable_slot__classroom__semester"),
            subject_code=F("session__timetable_slot__subject_mapping__subject__code"),
            subject_name=F("session__timetable_slot__subject_mapping__subject__name"),
        )
        .annotate(total=Count("id"), present=Count("id", filter=Q(status__in=PRESENT_STATUSES)),
                  absent=Count("id", filter=Q(status="A")))
        .order_by("academic_year", "semester", "subject_code")
    )
    results = [{**row, "percentage": round(row["present"] * 100 / row["total"], 2) if row["total"] else 0}
               for row in summary]
 
    total = sum(r["total"] for r in results)
    present = sum(r["present"] for r in results)
    return Response({"student": str(student.id),"overall_percentage": round(present * 100 / total, 2) if total else 0,"subjects": results,})
    
    
    
# ========================================
# NOTE: - STUDENTS -
# ========================================

@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def student_login_api_view(request):
    if request.method == "GET":
        return render(request, "Student/student_login.html")

    login_id = request.data.get("login_id")
    login_via = request.data.get("login_via", "register_number")  # 'register_number' | 'email'
    password = request.data.get("password")

    if not login_id or not password:
        messages.error(request,"Register number/email and password are required.")
        return redirect('student_login')
        return Response({"success": False, "message": "Register number/email and password are required."},status=status.HTTP_400_BAD_REQUEST,)
    ip_address = get_client_ip(request)
    device_info = get_device_info(request)

    # --------------------------------------------------
    # Find student
    # --------------------------------------------------
    user = None
    student_profile = None
    print(request.data)
    if login_via == "email":
        user = User.objects.filter(email__iexact=login_id).first()
        if user:
            student_profile = StudentProfile.objects.filter(college_user__user=user, college_user__role="student").select_related("college_user").first()
    else:
        student_profile = StudentProfile.objects.filter(roll_number__iexact=login_id).select_related("college_user__user").first()
        if student_profile:
            user = student_profile.college_user.user
    print(user)
    print(student_profile)
    if not user or not student_profile:
        print("checking")
        LoginAttempt.objects.create(user=None, ip_address=ip_address, user_agent=device_info["user_agent"], result="failed_password")
        messages.error(request,"Invalid credentials.")
        return redirect('student_login')
        return Response({"success": False, "message": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    # --------------------------------------------------
    # Check user / profile status
    # --------------------------------------------------
    if user.status != "active" or not user.is_active or not student_profile.is_active:
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="blocked")
        messages.error(request,"Unable to login.")
        return redirect('student_login')
        return Response({"success": False, "message": "Unable to login."}, status=status.HTTP_403_FORBIDDEN)

    # --------------------------------------------------
    # LoginSecurity / cooldown
    # --------------------------------------------------
    security, _ = LoginSecurity.objects.get_or_create(user=user)
    if security.is_in_cooldown():
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="cooldown")
        messages.error(request,f"Too many failed attempts. try after {security.cooldown_until}")
        return redirect('student_login')
        return Response({"success": False, "message": "Too many failed attempts.", "cooldown_until": security.cooldown_until},status=status.HTTP_429_TOO_MANY_REQUESTS,)

    # --------------------------------------------------
    # Authenticate password
    # --------------------------------------------------
    authenticated_user = authenticate(request=request, username=user.username, password=password)
    if authenticated_user is None:
        security.failed_attempts += 1
        if security.failed_attempts >= 5:
            security.status = "cooldown"
            security.cooldown_until = timezone.now() + timedelta(minutes=15)
        security.save()
        LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="failed_password")
        messages.error(request,"Invalid credentials.")
        return redirect('student_login')
        return Response({"success": False, "message": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)

    # Password correct — reset security counters
    security.failed_attempts = 0
    security.status = "active"
    security.cooldown_until = None
    security.save()
    
    if not user.password_updated:
        print("password upadate")
        request.session["pending_setup_user_id"] = str(user.id)
        request.session["setup_role"] = "student"
        request.session["otp_verified"] = False
        _otp, code = _issue_otp(user, purpose="password_reset", channel="email")
        _send_otp_email(user, code)
        print("after mail sent")
        return redirect("email-auth-verification")
        # return Response({"success": True,"requires_password_setup": True,"message": "First login detected. A verification code has been sent to your registered email.",},status=status.HTTP_200_OK,)

    # --------------------------------------------------
    # Trusted device check
    # --------------------------------------------------
    raw_device_token = request.COOKIES.get("device_token")
    trusted_device = None

    if raw_device_token:
        print("un trusted device")
        token_hash = hash_device_token(raw_device_token)
        trusted_device = TrustedDevice.objects.filter(user=user, device_token_hash=token_hash, is_active=True, is_trusted=True).first()
        if trusted_device and trusted_device.expires_at and trusted_device.expires_at < timezone.now():
            trusted_device.is_trusted = False
            trusted_device.save(update_fields=["is_trusted"])
            trusted_device = None
    if trusted_device:
        print("complete login")
        return _complete_login(request=request, user=user, device=trusted_device,ip_address=ip_address, device_info=device_info, new_device=False,)

    # --------------------------------------------------
    # Untrusted / new device → OTP (students don't get TOTP branch)
    # --------------------------------------------------
    LoginAttempt.objects.create(user=user, ip_address=ip_address, user_agent=device_info["user_agent"], result="new_device")
    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    OTPVerification.objects.filter(user=user, purpose="new_device", is_used=False).update(is_used=True)
    verification = OTPVerification.objects.create(user=user,purpose="new_device",channel="email",otp_hash=otp_hash,expires_at=timezone.now() + timedelta(minutes=5),)
    temporary_token = secrets.token_urlsafe(32)
    refresh = RefreshToken.for_user(user)
    request.session["pending_login"] = {"verification_id": str(verification.id),"temporary_token": temporary_token,}
    request.session["access_token"] = str(refresh.access_token)
    request.session["refresh_token"] = str(refresh)
    request.session["user_id"] = str(user.id)
    return redirect('student-dashboard')
    send_login_verification_otp_email(user, otp)
    return Response({"success": True,"requires_new_device_verification": True,"temporary_token": temporary_token,"message": "A verification code has been sent to your registered email.",},status=status.HTTP_200_OK,)


# --------------------------------------------------
# Student Dashboard
# --------------------------------------------------

def _build_timetable_grid(classroom):
    days = [dict(day_of_week=n, label=l) for n, l in TimetableSlot.DAYS_OF_WEEK]
    if not classroom:
        return [], []
    slots = (TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject","subject_mapping__teacher__college_user__user","teacher",).order_by("period_number", "day_of_week"))
    period_meta = {}
    for s in slots:
        period_meta.setdefault(s.period_number, {"period_number": s.period_number,"start_time": s.start_time.strftime("%H:%M"),"end_time": s.end_time.strftime("%H:%M"),})
    periods = [period_meta[p] for p in sorted(period_meta)]

    grid = {d["day_of_week"]: {} for d in days}
    for s in slots:
        mapping_teacher = s.subject_mapping.teacher
        staff_name, staff_designation = _staff_display(mapping_teacher)
        if not staff_name and s.teacher_id:
            staff_name = s.teacher.get_full_name() or s.teacher.username

        grid[s.day_of_week][s.period_number] = {"subject_code": s.subject_mapping.subject.code,"subject_short_name": s.subject_mapping.subject.short_name,"subject_name": s.subject_mapping.subject.name,"staff_name": staff_name,"staff_designation": staff_designation,}

    rows = []
    for d in days:
        cells = [grid[d["day_of_week"]].get(p["period_number"]) for p in periods]
        rows.append({"label": d["label"], "cells": cells})
    return periods, rows

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_dashboard(request):
    print("no student",request.user)
    student_profile = (StudentProfile.objects.filter(college_user__user=request.user).select_related("college_user__user", "college", "department").first())
    if not student_profile:
        return render(request, "Student/no_profile.html", status=404)
    data = StudentDashboardSerializer(student_profile).data
    classroom = (Classroom.objects.filter(college=student_profile.college,department=student_profile.department,year=student_profile.year,semester=student_profile.semester,section=student_profile.section,).first())
    periods, rows = _build_timetable_grid(classroom)
    context = {"student": data,"active_nav": "dashboard","classroom": classroom,"periods": periods,"rows": rows,}
    return render(request, "Student/dashboard.html", context)


PRESENT_STATUSES = ["P", "L", "OD"]
def get_student_profile(user):
    try:
        return (StudentProfile.objects.select_related("college", "department").get(college_user__user=user))
    except StudentProfile.DoesNotExist:
        raise NotFound("Student profile not found for this account.")
    
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_page(request):
    student = (StudentProfile.objects.select_related("college", "department").filter(college_user__user=request.user).first())
    data = StudentDashboardSerializer(student).data
    context = {"active_nav": "attendance","student": data,}
    return render(request, "Student/attendance.html", context)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_summary(request):
    student = get_student_profile(request.user)
    qs = StudentAttendance.objects.filter(student=student)
    total = qs.count()
    present = qs.filter(status="P").count()
    absent = qs.filter(status="A").count()
    late = qs.filter(status="L").count()
    on_duty = qs.filter(status="OD").count()
    attended = sum(count for st, count in[("P", present), ("L", late), ("OD", on_duty)]if st in PRESENT_STATUSES)
    percentage = round((attended / total) * 100, 2) if total else 0.0
    data = {"total_sessions": total,"present_count": present,"absent_count": absent,"late_count": late,"on_duty_count": on_duty,"percentage": percentage,}
    return Response(AttendanceSummarySerializer(data).data)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subject_attendance(request):
    student = get_student_profile(request.user)
    qs = (StudentAttendance.objects.filter(student=student).select_related("session__timetable_slot__subject_mapping__subject"))
    by_subject = {}
    for record in qs:
        subject = record.session.timetable_slot.subject_mapping.subject
        entry = by_subject.setdefault(subject.id, {"subject_code": subject.code,"subject_name": subject.name,"total": 0,"present": 0,})
        entry["total"] += 1
        if record.status in PRESENT_STATUSES:
            entry["present"] += 1
 
    results = []
    for entry in by_subject.values():
        entry["percentage"] = (round((entry["present"] / entry["total"]) * 100, 2) if entry["total"] else 0.0)
        results.append(entry)
    results.sort(key=lambda r: r["subject_name"])
    serializer = SubjectAttendanceSerializer(results, many=True)
    return Response(serializer.data)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def attendance_calendar(request):
    student = get_student_profile(request.user)
    today = timezone.localdate()
    month_param = request.query_params.get("month")
    if month_param:
        try:
            year_str, month_str = month_param.split("-")
            year, month = int(year_str), int(month_str)
            if not (1 <= month <= 12):
                raise ValueError
        except (ValueError, AttributeError):
            return Response(
                {"detail": "month must be in YYYY-MM format."},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        year, month = today.year, today.month
 
    first_day = date(year, month, 1)
    days_in_month = cal.monthrange(year, month)[1]
    last_day = date(year, month, days_in_month)
    records = (StudentAttendance.objects.filter(student=student, session__date__range=(first_day, last_day)).select_related("session"))
    status_by_date = {}
    for record in records:
        d = record.session.date
        status_by_date.setdefault(d, []).append(record.status)
 
    def day_status(d):
        if d > today:
            return "future", None
        statuses = status_by_date.get(d)
        if not statuses:
            return "holiday", "No class scheduled"
        if "A" in statuses:
            return "absent", "Absent"
        if "OD" in statuses:
            return "on_duty", "On Duty"
        if "L" in statuses:
            return "late", "Late"
        if "P" in statuses:
            return "present", "Present"
        return "holiday", "No class scheduled"
 
    cal_module = cal.Calendar(firstweekday=0)  # Monday-first, matches TimetableSlot.DAYS_OF_WEEK
    weeks = []
    for week in cal_module.monthdatescalendar(year, month):
        week_data = []
        for d in week:
            st, label = day_status(d)
            week_data.append({"date": d,"day_number": d.day,"in_month": d.month == month,"is_today": d == today,"status": st,"status_label": label,})
        weeks.append(week_data)
 
    prev_month_date = (first_day - timedelta(days=1)).replace(day=1)
    next_month_date = last_day + timedelta(days=1)
    data = {"month_label": first_day.strftime("%B %Y"),"month": f"{year:04d}-{month:02d}","prev_month": prev_month_date.strftime("%Y-%m"),"next_month": next_month_date.strftime("%Y-%m"),"weeks": weeks,}
    return Response(AttendanceCalendarSerializer(data).data)


def _staff_display(staff_profile):
    if not staff_profile:
        return None, None
    user = getattr(getattr(staff_profile, "college_user", None), "user", None)
    if user:
        name = user.get_full_name() or user.username
    else:
        name = getattr(staff_profile, "full_name", None) or str(staff_profile)
    designation = getattr(staff_profile, "designation", None)
    return name, designation



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_timetable_view(request):
    student = get_object_or_404(StudentProfile, college_user__user=request.user)
    data = StudentDashboardSerializer(student).data
    classroom = (Classroom.objects.filter(college=student.college,department=student.department,year=student.year,semester=student.semester,section=student.section,).first())
    days = [dict(day_of_week=n, label=l) for n, l in TimetableSlot.DAYS_OF_WEEK]
    if not classroom:
        return render(request, "Student/timetable.html", {"active_nav": "timetable","classroom": None,"days": days,"periods": [],"rows": [],})
    slots = (TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject","subject_mapping__teacher__college_user__user",  "teacher").order_by("period_number", "day_of_week"))
    # unique periods, in order, with time range (first occurrence wins)
    period_meta = {}
    for s in slots:
        period_meta.setdefault(s.period_number, {"period_number": s.period_number,"start_time": s.start_time.strftime("%H:%M"),"end_time": s.end_time.strftime("%H:%M"),})
    periods = [period_meta[p] for p in sorted(period_meta)]
    # grid[day_of_week][period_number] = cell data
    grid = {d["day_of_week"]: {} for d in days}
    print(grid)
    for s in slots:
        mapping_teacher = s.subject_mapping.teacher
        staff_name, staff_designation = _staff_display(mapping_teacher)
        if not staff_name and s.teacher_id:
            staff_name = s.teacher.get_full_name() or s.teacher.username
        grid[s.day_of_week][s.period_number] = {"subject_code": s.subject_mapping.subject.code,"subject_short_name": s.subject_mapping.subject.short_name,"subject_name": s.subject_mapping.subject.name,"staff_name": staff_name, "staff_designation": staff_designation}
        print(grid[s.day_of_week][s.period_number])
    # pre-build day rows with an ordered list of cells matching `periods`,
    # so the template just zips them with no dict lookups / custom tags needed
    rows = []
    for d in days:
        cells = []
        for p in periods:
            cells.append(grid[d["day_of_week"]].get(p["period_number"]))
        rows.append({"label": d["label"], "cells": cells})

    return render(request, "Student/timetable.html", {"active_nav": "timetable","classroom": classroom,"days": days,"periods": periods,"rows": rows,"student":data})




def _generate_otp():
    return f"{random.randint(0, 999999):06d}"


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_password_change_otp(request):
    serializer = RequestPasswordOTPSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = request.user
    OTPVerification.objects.filter(user=user, purpose="password_reset", is_used=False).update(is_used=True)
    raw_otp = _generate_otp()
    OTPVerification.objects.create(user=user,purpose="password_reset",channel="email",otp_hash=make_password(raw_otp),max_attempts=OTP_MAX_ATTEMPTS,expires_at=timezone.now() + timedelta(minutes=OTP_VALIDITY_MINUTES),)
    send_password_reset_otp_email(user_name=user.get_full_name() or user.email,user_email=user.email,otp=raw_otp,expires_in_minutes=OTP_VALIDITY_MINUTES,)
    return Response({"detail": "OTP sent to your registered email.","email_hint": _mask_email(user.email),"expires_in_minutes": OTP_VALIDITY_MINUTES,})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def verify_password_change_otp(request):
    serializer = VerifyPasswordOTPSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = request.user
    otp_input = serializer.validated_data["otp"]
    new_password = serializer.validated_data["new_password"]
    otp_record = (OTPVerification.objects.filter(user=user, purpose="password_reset", is_used=False).order_by("-created_at").first())

    if not otp_record:
        return Response({"detail": "No active OTP request found. Please request a new one."},status=status.HTTP_400_BAD_REQUEST,)

    if otp_record.is_expired():
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used"])
        return Response({"detail": "OTP has expired. Please request a new one."},status=status.HTTP_400_BAD_REQUEST,)

    if otp_record.attempts >= otp_record.max_attempts:
        otp_record.is_used = True
        otp_record.save(update_fields=["is_used"])
        return Response({"detail": "Too many incorrect attempts. Please request a new OTP."},status=status.HTTP_400_BAD_REQUEST,)

    if not check_password(otp_input, otp_record.otp_hash):
        otp_record.attempts += 1
        otp_record.save(update_fields=["attempts"])
        remaining = otp_record.max_attempts - otp_record.attempts
        return Response({"detail": f"Incorrect OTP. {remaining} attempt(s) remaining."},status=status.HTTP_400_BAD_REQUEST,)

    # OTP correct — finalize
    otp_record.is_used = True
    otp_record.verified_at = timezone.now()
    otp_record.save(update_fields=["is_used", "verified_at"])

    user.set_password(new_password)
    user.password_updated = True
    user.save(update_fields=["password", "password_updated"])
    return Response({"detail": "Password changed successfully."})


def _mask_email(email):
    try:
        local, domain = email.split("@")
    except ValueError:
        return email
    if len(local) <= 2:
        masked = local[0] + "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_profile_view(request):
    student_profile = (StudentProfile.objects.filter(college_user__user=request.user).select_related("college_user__user", "college", "department").first())
    if not student_profile:
        return render(request, "Student/no_profile.html", status=404)
    data = StudentProfileSerializer(student_profile).data
    return render(request, "Student/profile.html", {"student": data,"active_nav": "profile",})


# ---------------------------------------------------------------------------
# Promotion list — Department -> Year -> Students, with select checkboxes
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_promotion(request):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access = get_promotion_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have permission to promote students.")
 
    departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    
    if access["level"] == "class":
        departments = departments.filter(id=access["department"].id)
    all_students = scope_promotion_students(StudentProfile.objects.filter(college=college, is_active=True), access).select_related("college_user", "college_user__user").order_by("year", "semester", "roll_number")
    by_dept = {}
    for stu in all_students:
        by_dept.setdefault(stu.department_id, []).append(stu)
    department_groups = []
    for dept in departments:
        students = StudentProfile.objects.filter(department=dept, college=college_user.college, is_active=True).select_related("college_user", "college_user__user").order_by("year", "semester", "roll_number")
        year_groups = []
        for academic_year, students_in_year in groupby(students, key=lambda s: s.academic_year or "Unspecified"):
            year_groups.append({"academic_year": academic_year, "students": list(students_in_year)})
        department_groups.append({"department": dept,"year_groups": year_groups,"student_count": len(students),})
    academic_years = AcademicYear.objects.filter(college=college)
    context = {"department_groups": department_groups,"academic_years": academic_years,"current_academic_year": AcademicYear.objects.filter(college=college_user.college, is_current=True).first(),"target_years": access["target_years"],"can_create_academic_year": access["can_create_academic_year"],"is_class_advisor_view": access["level"] == "class",}
    return render(request, "Admin/student_promotion.html", context)
 
 
# ---------------------------------------------------------------------------
# Bulk promote — updates year / semester / section / academic_year at once
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def promote_students(request):
    college_user = CollegeUser.objects.get(user=request.user)
    college = college_user.college
    access = get_promotion_access(college_user)
    if access["level"] == "none":
        raise PermissionDenied("You do not have permission to promote students.")
 
    data = request.data
 
    if access["level"] == "class":
        # 1) every selected student must belong to the advisor's own class
        ids = data.get("students")
        if not isinstance(ids, list) or not ids:
            return Response({"students": "Select at least one student."}, status=status.HTTP_400_BAD_REQUEST)
        uuids = {valid_uuid(i) for i in ids}
        if None in uuids:
            return Response({"students": "Invalid student selection."}, status=status.HTTP_400_BAD_REQUEST)
        in_scope = StudentProfile.objects.filter(id__in=uuids, college=college,department=access["department"], year=access["year"],).count()
        if in_scope != len(uuids):
            return Response({"students": "You can only promote students of your own class."},
                            status=status.HTTP_403_FORBIDDEN)
 
        # 2) target year: same year or the next one only
        year = data.get("year")
        if year not in (None, ""):
            try:
                year = int(year)
            except (TypeError, ValueError):
                return Response({"year": "Invalid year."}, status=status.HTTP_400_BAD_REQUEST)
            if year not in {v for v, _ in access["target_years"]}:
                return Response({"year": "You can only promote to your own year or the next year."},
                                status=status.HTTP_403_FORBIDDEN)
 
        # 3) target academic year must already exist (only admins create academic years)
        ay_name = (data.get("academic_year") or "").strip()
        if ay_name and not AcademicYear.objects.filter(college=college, name=ay_name).exists():
            return Response({"academic_year": "That academic year does not exist. Ask an admin to create it first."},status=status.HTTP_403_FORBIDDEN)
    serializer = PromoteStudentsSerializer(data=request.data, context={"college": college_user.college})
    if serializer.is_valid():
        r = serializer.save()
        msg = f"{r['promoted']} student(s) promoted"
        if r["classrooms_created"]:
            msg += f", {r['classrooms_created']} new classroom(s) created"
        return Response({"message": msg + ".", "skipped": r["skipped"], **r})
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



FULL_ACCESS_ROLES = ("master_admin", "office_admin")
 
 
# ===========================================================================
# ACCESS RULES
# ===========================================================================
def _get_fee_access(college_user):
    if college_user.role in FULL_ACCESS_ROLES:
        return {"level": "full", "department": None, "year": None,
                "can_open_detail": True, "can_edit": True}
 
    staff = (StaffProfile.objects.filter(college_user=college_user, is_active=True, department__isnull=False).select_related("department").first())
    if staff and staff.staff_role == "hod":
        return {"level": "department", "department": staff.department, "year": None,"can_open_detail": False, "can_edit": False}
    if staff and staff.staff_role == "class_advisor" and staff.advisor_year:
        return {"level": "class", "department": staff.department, "year": staff.advisor_year,"can_open_detail": False, "can_edit": False}
    return {"level": "none", "department": None, "year": None,"can_open_detail": False, "can_edit": False}
 
 
def _scope_students(qs, access):
    if access["level"] == "department":
        return qs.filter(department=access["department"])
    if access["level"] == "class":
        return qs.filter(department=access["department"], year=access["year"])
    if access["level"] == "none":
        return qs.none()
    return qs
 
 
def _fee_user_access(user):
    cu = CollegeUser.objects.filter(user=user).select_related("college").first()
    return (cu, _get_fee_access(cu)) if cu else (None, None)
 
 
def _require_page_access(request, flag=None):
    """For HTML pages: raises Django's PermissionDenied -> normal 403 page."""
    cu, access = _fee_user_access(request.user)
    if not cu or access["level"] == "none" or (flag and not access[flag]):
        raise PermissionDenied("You do not have access to this page.")
    return cu, access
 
 
class CanViewFees(BasePermission):
    """For JSON endpoints."""
    message = "You do not have access to fee details."
    flag = None
 
    def has_permission(self, request, view):
        cu, access = _fee_user_access(request.user)
        if not cu or access["level"] == "none":
            return False
        request.college_user, request.fee_access = cu, access
        return access[self.flag] if self.flag else True
 
 
class CanOpenFeeDetail(CanViewFees):
    message = "Only master admin and office admin can open fee details."
    flag = "can_open_detail"
 
 
class CanEditFees(CanViewFees):
    message = "You do not have permission to edit fee details."
    flag = "can_edit"
 
 
# ===========================================================================
# BUILDERS: return SERIALIZED data. Used by both the HTML page and the JSON API
# so the two can never drift apart.
# ===========================================================================
def _invoice_queryset():
    return (StudentFeeInvoice.objects.select_related("fee_structure", "fee_structure__department").prefetch_related(Prefetch("items", queryset=StudentFeeInvoiceItem.objects.select_related("category", "concession")),Prefetch("payments", queryset=FeePayment.objects.filter(status="success")),Prefetch("payments",queryset=FeePayment.objects.select_related("settlement_item").order_by("-created_at"),to_attr="all_payments"),))
 
 
def build_fee_list(college_user, access, params):
    query = FeeListQuerySerializer(data=params)
    validated = query.validated_data if query.is_valid() else {}
    payment_status_filter = validated.get("payment_status", "")
    department_filter = validated.get("department")
 
    base_qs = _scope_students(StudentProfile.objects.filter(college=college_user.college, is_active=True), access)
    qs = _apply_filters(base_qs, params).select_related("college_user", "college_user__user", "department")
    invoices_prefetch = Prefetch("fee_invoices",queryset=StudentFeeInvoice.objects.exclude(status="cancelled").prefetch_related(Prefetch("payments", queryset=FeePayment.objects.filter(status="success"))),to_attr="active_invoices",)
    all_students = list(qs.prefetch_related(invoices_prefetch))
    for stu in all_students:
        stu.payment_status, stu.total_due, stu.total_paid = _compute_payment_status(stu)
 
    total = len(all_students)
    counts = {k: sum(1 for s in all_students if s.payment_status == k) for k in ("paid", "partial", "unpaid")}
    pct = lambda n: round((n / total) * 100, 1) if total else 0.0
    summary = {"total": total, **{k: {"count": c, "percentage": pct(c)} for k, c in counts.items()}}
 
    visible = ([s for s in all_students if s.payment_status == payment_status_filter]
               if payment_status_filter else all_students)
 
    all_departments = Department.objects.filter(is_active=True, college=college_user.college).order_by("name")
    if access["level"] in ("department", "class"):
        all_departments = all_departments.filter(id=access["department"].id)
    departments = all_departments.filter(id=department_filter) if department_filter else all_departments
 
    by_dept = {}
    for stu in visible:
        by_dept.setdefault(stu.department_id, []).append(stu)
 
    groups = []
    for dept in departments:
        students = _sort_students(by_dept.get(dept.id, []))
        groups.append({"department": dept,"student_count": len(students),"year_groups": [{"academic_year": ay, "students": list(g)} for ay, g in groupby(students, key=lambda s: s.academic_year or "Unspecified")],})
 
    academic_years = (_scope_students(StudentProfile.objects.filter(college=college_user.college), access).exclude(academic_year="").values_list("academic_year", flat=True).distinct().order_by("-academic_year"))
    data = FeeListResponseSerializer({"access_level": access["level"],"can_open_detail": access["can_open_detail"],"summary": summary,"filters": {"departments": [{"id": str(d.id), "name": d.name} for d in all_departments],"academic_years": list(academic_years),},"groups": groups,}).data
 
    selected = {"selected_department": str(department_filter) if department_filter else "","selected_academic_year": params.get("academic_year", ""),"selected_year": params.get("year", ""),"selected_semester": params.get("semester", ""),"selected_payment_status": payment_status_filter,}
    return data, selected
 
 
def build_fee_detail(college_user, student_id):
    student = get_object_or_404(StudentProfile.objects.select_related("college_user__user", "department"),id=student_id, college=college_user.college,)
    invoices = list(_invoice_queryset().filter(student=student).order_by("-generated_at"))
 
    live = [i for i in invoices if i.status != "cancelled"]
    amounts = [invoice_amounts(i) for i in live]
    student.active_invoices = live
    overall_status, _, _ = _compute_payment_status(student)
 
    structures = (FeeStructure.objects.filter(college=student.college, is_active=True, year=student.year).filter(Q(department=student.department) | Q(department__isnull=True)).select_related("department").prefetch_related("items__category").order_by("-academic_year")) if student.year else FeeStructure.objects.none()
 
    return StudentFeeDetailSerializer({"student": student,"summary": {"total_billed": sum((a["net"] for a in amounts), Decimal("0")),"total_paid": sum((a["paid"] for a in amounts), Decimal("0")),"total_balance": sum((a["balance"] for a in amounts), Decimal("0")),"overall_status": overall_status,},"structures": structures,"concessions": FeeConcession.objects.filter(student=student, is_active=True).select_related("category"),"invoices": invoices,}).data
 
 
# ===========================================================================
# HTML PAGES  (serializer output -> template context)
# ===========================================================================
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_list_page(request):
    college_user, access = _require_page_access(request)
    data, selected = build_fee_list(college_user, access, request.GET)
    context = {"department_groups": data["groups"],"payment_summary": data["summary"],"departments": data["filters"]["departments"],"academic_years": data["filters"]["academic_years"],"access_level": data["access_level"],"can_open_detail": data["can_open_detail"],**selected,}
    return render(request, "Admin/fee_list.html", context)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_student_detail_page(request, student_id):
    college_user, _ = _require_page_access(request, flag="can_open_detail")
    data = build_fee_detail(college_user, student_id)
    context = {"student": data["student"],"summary": data["summary"],"structures": data["structures"],"concessions": data["concessions"],"invoices": data["invoices"],}
    print(context)
    return render(request, "Admin/fee_student_detail.html", context)
 
 
# ===========================================================================
# JSON API
# ===========================================================================
@api_view(["GET"])
@permission_classes([IsAuthenticated, CanViewFees])
def fee_list_api(request):
    data, _ = build_fee_list(request.college_user, request.fee_access, request.query_params)
    return Response(data)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated, CanOpenFeeDetail])
def fee_student_detail_api(request, student_id):
    return Response(build_fee_detail(request.college_user, student_id))
 
 
@api_view(["PATCH", "POST"])
@permission_classes([IsAuthenticated, CanEditFees])
def fee_invoice_update(request, invoice_id):
    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student__college=request.college_user.college)
    serializer = InvoiceUpdateSerializer(invoice, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    fresh = _invoice_queryset().get(id=invoice.id)
    return Response(StudentFeeInvoiceSerializer(fresh).data)
 
 
@api_view(["PATCH", "POST"])
@permission_classes([IsAuthenticated, CanEditFees])
def fee_payment_update(request, payment_id):
    payment = get_object_or_404(FeePayment.objects.select_related("invoice", "settlement_item"),id=payment_id, student__college=request.college_user.college,)
    serializer = PaymentUpdateSerializer(payment, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    payment = serializer.save()
    return Response({"payment": FeePaymentSerializer(payment).data,
                     "invoice_status": payment.invoice.status})

# ---------------------------------------------------------------------------
# Bulk promote — updates year / semester / section / academic_year at once
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# PAGE
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def create_fee_structure_page(request):
    college_user = (CollegeUser.objects.select_related("college").filter(user=request.user, status="active").first())
    if not college_user:
        return Response({"detail": "No college found for this user."}, status=403)

    college = college_user.college
    departments = Department.objects.filter(college=college, is_active=True).order_by("name")
    academic_years = AcademicYear.objects.filter(college=college).order_by("-start_date")
    current_academic_year = academic_years.filter(is_current=True).first()
    fee_categories = list(FeeCategory.objects.filter(college=college, is_active=True).order_by("name").values("id", "name", "code", "is_optional"))

    context = {"college": college.id,"departments": departments,"academic_years": academic_years,"current_academic_year": current_academic_year,"fee_categories": fee_categories}
    return render(request, "Admin/create_fee_structure.html", context)
 
# ---------------------------------------------------------------------------
# API — create (writes to all three tables in one atomic call)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_fee_structure_api(request):
    serializer = FeeStructureCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    fee_structure = serializer.save()
    output = FeeStructureDetailSerializer(fee_structure)
    return Response(output.data, status=status.HTTP_201_CREATED)
 
 
# ---------------------------------------------------------------------------
# API — list (for a fee-structures table / to check what already exists)
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_structure_list_api(request):
    college_id = request.query_params.get("college")
    if not college_id:
        return Response({"detail": "college is required."}, status=status.HTTP_400_BAD_REQUEST)
 
    qs = (FeeStructure.objects.filter(college_id=college_id).select_related("department").prefetch_related("items__category").order_by("-created_at"))
    department_id = request.query_params.get("department")
    if department_id:
        qs = qs.filter(department_id=department_id)
 
    year = request.query_params.get("year")
    if year:
        qs = qs.filter(year=year)
 
    academic_year = request.query_params.get("academic_year")
    if academic_year:
        qs = qs.filter(academic_year=academic_year)
 
    serializer = FeeStructureDetailSerializer(qs, many=True)
    return Response(serializer.data)
 
 
# ---------------------------------------------------------------------------
# API — existing fee category codes for a college (optional: power an
# autocomplete on the "code" input so staff reuse "TUITION" instead of
# accidentally creating "TUTION")
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_categories_api(request):
    college_id = request.query_params.get("college")
    if not college_id:
        return Response({"detail": "college is required."}, status=status.HTTP_400_BAD_REQUEST)
    categories = FeeCategory.objects.filter(college_id=college_id, is_active=True).order_by("name")
    data = [{"id": str(c.id), "name": c.name, "code": c.code, "is_optional": c.is_optional}for c in categories]
    return Response(data)


# ---------------------------------------------------------------------------
# PAGE
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def assign_fee_structure_page(request):
    print(request.user)
    print(request.user)
    college = CollegeUser.objects.get(user_id=request.user).college  # adjust to match your auth/session setup
    fee_structures = (FeeStructure.objects.filter(college=college, is_active=True).select_related("department", "academic_year").order_by("-academic_year__start_date", "year", "department__short_name"))
    return render(request,"Admin/assign_fee_structure.html",{"college": college.id,"fee_structures": fee_structures,},)
 
 
# ---------------------------------------------------------------------------
# API — eligible students for a fee structure
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def eligible_students(request, fee_structure_id):
    try:
        fee_structure = FeeStructure.objects.select_related("department").get(id=fee_structure_id, is_active=True)
    except FeeStructure.DoesNotExist:
        return Response({"detail": "Fee structure not found."}, status=status.HTTP_404_NOT_FOUND)
 
    raw_semester = request.query_params.get("semester")
    if raw_semester in (None, ""):
        semester = None
    else:
        try:
            semester = int(raw_semester)
        except ValueError:
            return Response({"semester": "Must be an integer."}, status=status.HTTP_400_BAD_REQUEST)
 
    if fee_structure.billing_cycle == "semester" and semester is None:
        return Response({"semester": "Semester is required to check invoiced status for a semester-wise fee structure."},status=status.HTTP_400_BAD_REQUEST,)
 
    students_qs = (StudentProfile.objects.filter(college_id=fee_structure.college_id,year=fee_structure.year,is_active=True,status="active",).select_related("college_user__user", "department"))
    if fee_structure.department_id:
        students_qs = students_qs.filter(department_id=fee_structure.department_id)
 
    invoiced_ids = set(StudentFeeInvoice.objects.filter(fee_structure=fee_structure, semester=semester).values_list("student_id", flat=True))
    serializer = EligibleStudentSerializer(students_qs.order_by("roll_number", "admission_number"),many=True,context={"invoiced_student_ids": invoiced_ids},)
    return Response({"fee_structure": {"id": str(fee_structure.id),"billing_cycle": fee_structure.billing_cycle,"academic_year": fee_structure.academic_year.name,"year": fee_structure.year,"department": fee_structure.department.short_name if fee_structure.department_id else "All Departments",},"students": serializer.data,})
 
 
# ---------------------------------------------------------------------------
# API — assign fee structure to selected students (generates invoices)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def assign_fee_structure(request):
    serializer = AssignFeeStructureSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
 
    fee_structure = data["fee_structure"]
    semester = data["semester"]
    due_date = data["due_date"]
    students = data["students"]
 
    created, skipped = [], []
    for student in students:
        try:
            invoice = generate_invoice_for_student(student=student,fee_structure=fee_structure,semester=semester,due_date=due_date,)
            created.append(invoice)
        except InvoiceAlreadyExists:
            skipped.append({"student_id": str(student.id),"admission_number": student.admission_number,"reason": "Invoice already exists for this fee structure and semester.",})
    return Response({"created_count": len(created),"skipped_count": len(skipped),"invoices": StudentFeeInvoiceOutputSerializer(created, many=True).data,"skipped": skipped,},status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,)


def _get_student_profile(user):
    try:
        print(user.id)
        college_user = CollegeUser.objects.get(user_id=user.id,role='student')
        student = StudentProfile.objects.get(college_user=college_user)
        return student
    except AttributeError:
        raise Http404("No student profile for this user.")
 
# ---------------------------------------------------------------------------
# PAGES
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_fee_invoices_page(request):
    print(request.user)
    student = _get_student_profile(request.user)
    student_profile = StudentProfileSerializer(student)
    invoices_qs = (StudentFeeInvoice.objects.filter(student=student.id).select_related("fee_structure__department").prefetch_related("payments").order_by("-generated_at"))
    print(invoices_qs)
    invoices = StudentFeeInvoiceListSerializer(invoices_qs, many=True).data
    total_due = sum(float(inv["balance_due"]) for inv in invoices)
    overdue_count = sum(1 for inv in invoices if inv["status"] == "overdue")
    pending_count = sum(1 for inv in invoices if inv["status"] in ("pending", "partial", "overdue"))
    return render(request,"Student/fee_invoices.html",{"student_profile": student_profile.data,"invoices": invoices,"total_due": total_due,"overdue_count": overdue_count,"pending_count": pending_count,},)
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_fee_invoice_detail_page(request, invoice_id):
    student = _get_student_profile(request.user)
    invoice = get_object_or_404(StudentFeeInvoice.objects.select_related("fee_structure__department").prefetch_related("items__category", "items__concession", "payments"),id=invoice_id,student=student,)
    data = StudentFeeInvoiceDetailSerializer(invoice).data
    return render(request,"Student/fee_invoice_detail.html",{"student_profile": student,"invoice": data,},)
 
 
 
 
# ---------------------------------------------------------------------------
# API — "Pay Now"
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_pay_invoice(request, invoice_id):
    student = _get_student_profile(request.user)
    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student=student)
    if invoice.status in ("waived", "cancelled"):
        return Response({"detail": "This invoice has been " + invoice.get_status_display().lower() + " and cannot be paid."},status=status.HTTP_400_BAD_REQUEST,)
    try:
        link = generate_payment_link(invoice=invoice, created_by=None)
    except NothingToPayError:
        return Response({"detail": "This invoice has no outstanding balance."},status=status.HTTP_400_BAD_REQUEST,)
 
    return Response({"redirect_url": link.url,"amount": str(link.amount),"expires_at": link.expires_at,})

PAYMENT_MODE_OPTIONS = [("card", "Credit / Debit Card"),("upi", "UPI"),("bank_transfer", "Bank Transfer"),]
 
# ---------------------------------------------------------------------------
# PAGE — payment summary (shown right after Pay Now, before the gateway)
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_payment_summary_page(request, invoice_id, transaction_id):
    student = _get_student_profile(request.user)
    print(student)
    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student=student)
    history = get_object_or_404(PaymentHistory, transaction_id=transaction_id, invoice=invoice, student=student)
    if history.is_callback_updated:
        # Already completed (e.g. the student hit back/refresh) — nothing more to do here.
        return redirect("student-fee-invoice-detail-page", invoice_id=invoice.id)
 
    if history.callback_status == "cancelled":
        # Superseded by a newer Pay Now click — don't let a stale tab pay against it.
        return redirect(f"{reverse('student-fee-invoice-detail-page', args=[invoice.id])}?expired=1")
 
    return render(request,"Student/fee_payment_summary.html",{"student_profile": student,"invoice": invoice,"transaction_id": transaction_id,"amount": history.amount,},)
 
 
# ---------------------------------------------------------------------------
# PAGE — mock gateway (stand-in until a real gateway is wired up)
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def payment_gateway_mock_page(request, transaction_id):
    student = _get_student_profile(request.user)
    history = get_object_or_404(PaymentHistory, transaction_id=transaction_id, student=student)
 
    if history.is_callback_updated:
        return redirect("student-fee-invoices-page")
 
    if history.callback_status == "cancelled":
        return redirect(f"{reverse('student-fee-invoice-detail-page', args=[history.invoice_id])}?expired=1")
 
    payee_user = student.college_user.user
    payee_name = payee_user.get_full_name() or payee_user.username
 
    return render(request,"Student/payment_gateway_mock.html",{"transaction_id": transaction_id,"amount": history.amount,"payee_name": payee_name,"invoice_number": history.invoice.invoice_number,"payment_mode_options": PAYMENT_MODE_OPTIONS,},)
 
 
# ---------------------------------------------------------------------------
# API — invoice list/detail (JSON, same data as the pages)
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_student_fee_invoices(request):
    student = _get_student_profile(request.user)
    invoices_qs = (
        StudentFeeInvoice.objects.filter(student=student)
        .select_related("fee_structure__department")
        .prefetch_related("payments")
        .order_by("-generated_at")
    )
    return Response(StudentFeeInvoiceListSerializer(invoices_qs, many=True).data)
 
 
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_student_fee_invoice_detail(request, invoice_id):
    student = _get_student_profile(request.user)
    invoice = get_object_or_404(StudentFeeInvoice.objects.select_related("fee_structure__department").prefetch_related("items__category", "items__concession", "payments"),id=invoice_id,student=student,)
    return Response(StudentFeeInvoiceDetailSerializer(invoice).data)
 
 
# ---------------------------------------------------------------------------
# API — initiate payment (Pay Now button)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_initiate_payment(request, invoice_id):
    student = _get_student_profile(request.user)
    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student=student)
 
    if invoice.status in ("waived", "cancelled"):
        return Response({"detail": "This invoice has been " + invoice.get_status_display().lower() + " and cannot be paid."},status=status.HTTP_400_BAD_REQUEST,)
 
    try:
        history = initiate_online_payment(invoice=invoice)
    except NothingToPayError:
        return Response({"detail": "This invoice has no outstanding balance."},status=status.HTTP_400_BAD_REQUEST,)
    return Response({"redirect_url": reverse("student-payment-summary-page",kwargs={"invoice_id": invoice.id, "transaction_id": history.transaction_id},),"transaction_id": history.transaction_id,"amount": str(history.amount),})
 
 
# ---------------------------------------------------------------------------
# API — mock gateway callback (Success / Failure buttons)
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_gateway_callback(request, transaction_id):
    student = _get_student_profile(request.user)
    result = request.data.get("result")
    payment_mode = request.data.get("payment_mode")
 
    if result not in ("success", "failed"):
        return Response({"result": "Must be 'success' or 'failed'."}, status=status.HTTP_400_BAD_REQUEST)
    if payment_mode not in dict(PAYMENT_MODE_OPTIONS):
        return Response({"payment_mode": "Invalid payment mode."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        history = process_mock_gateway_callback(
            transaction_id=transaction_id, result=result, payment_mode=payment_mode, student=student
        )
    except InvalidPaymentAttempt:
        return Response({"detail": "Payment attempt not found."}, status=status.HTTP_404_NOT_FOUND)
    except PaymentAttemptExpired:
        return Response({"detail": "This payment link has expired because a newer one was generated. Please start again from the invoice."},status=status.HTTP_410_GONE,)
    
    settlement_batch_number = None
    if history.callback_status == "success" and history.fee_payment_id:
        settlement_item = getattr(history.fee_payment, "settlement_item", None)
        if settlement_item:
            settlement_batch_number = settlement_item.batch.batch_number
 
    return Response({"status": history.callback_status,"settlement_batch_number": settlement_batch_number,"redirect_url": reverse("student-fee-invoices-page"),})
 
 

UNASSIGNED_DEPARTMENT = SimpleNamespace(id="", name="Unassigned", short_name="—")
def _get_college(request):
    print("REQUEST: ===== ")
    print(request)
    
    college = CollegeUser.objects.get(user_id=request.user).college
    return college
 
 
# ---------------------------------------------------------------------------
# STUDENT TRANSACTION HISTORY — every FeePayment for the college, grouped
# Department -> Academic Year -> transactions, exactly like the Students
# roster groups Department -> Academic Year -> students.
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_fee_transactions_page(request):
    college = _get_college(request)
    departments = Department.objects.filter(college=college).order_by("name")
 
    selected_department = request.GET.get("department", "")
    selected_academic_year = request.GET.get("academic_year", "")
    selected_status = request.GET.get("status", "")
    selected_payment_mode = request.GET.get("payment_mode", "")
 
    payments_qs = (FeePayment.objects.filter(student__college=college).select_related("student__college_user__user","student__department","invoice",).order_by("-created_at"))
 
    if selected_department:
        payments_qs = payments_qs.filter(student__department_id=selected_department)
    if selected_academic_year:
        payments_qs = payments_qs.filter(invoice__academic_year=selected_academic_year)
    if selected_status:
        payments_qs = payments_qs.filter(status=selected_status)
    if selected_payment_mode:
        payments_qs = payments_qs.filter(payment_mode=selected_payment_mode)
 
    academic_years = (StudentFeeInvoice.objects.filter(student__college=college).exclude(academic_year="").values_list("academic_year", flat=True).distinct().order_by("-academic_year"))
 
    dept_map = OrderedDict()
    for payment in payments_qs:
        dept = payment.student.department or UNASSIGNED_DEPARTMENT
        dept_entry = dept_map.setdefault(dept.id, {"department": dept, "transaction_count": 0, "year_map": OrderedDict()})
        dept_entry["transaction_count"] += 1
 
        academic_year = payment.invoice.academic_year or "—"
        year_entry = dept_entry["year_map"].setdefault(academic_year, {"academic_year": academic_year, "transactions": []})
        year_entry["transactions"].append(payment)
 
    department_groups = [
        {"department": entry["department"],"transaction_count": entry["transaction_count"],"year_groups": list(entry["year_map"].values()),}
        for entry in dept_map.values()
    ]
 
    return render(request,"Admin/fee_transactions.html",{"departments": departments,"academic_years": academic_years,"status_choices": FeePayment.STATUS_CHOICES,"payment_mode_choices": FeePayment.PAYMENT_MODE_CHOICES,"selected_department": selected_department,"selected_academic_year": selected_academic_year,"selected_status": selected_status,"selected_payment_mode": selected_payment_mode,"department_groups": department_groups,},)
 
 
# ---------------------------------------------------------------------------
# SETTLEMENT BATCHES — list, filterable by status
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_settlement_batches_page(request):
    college = _get_college(request)
    selected_status = request.GET.get("status", "")
 
    batches_qs = SettlementBatch.objects.filter(college=college).order_by("-created_at")
    if selected_status:
        batches_qs = batches_qs.filter(status=selected_status)

    return render(request,"Admin/settlement_batches.html",{"batches": batches_qs,"status_choices": SettlementBatch.STATUS_CHOICES,"selected_status": selected_status,},)
 
 
# ---------------------------------------------------------------------------
# SETTLEMENT BATCH DETAIL — the batch's own transaction list
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def admin_settlement_batch_detail_page(request, batch_id):
    college = _get_college(request)
    batch = get_object_or_404(SettlementBatch, id=batch_id, college=college)
    selected_settled = request.GET.get("settled", "")  # "", "yes", "no"
    items_qs = batch.items.select_related("fee_payment__student__college_user__user","fee_payment__student__department","fee_payment__invoice",).order_by("-created_at")
 
    if selected_settled == "yes":
        items_qs = items_qs.filter(is_settled=True)
    elif selected_settled == "no":
        items_qs = items_qs.filter(is_settled=False)
 
    return render(request,"Admin/settlement_batch_detail.html",{"batch": batch,"items": items_qs,"selected_settled": selected_settled,},)


 
@api_view(["GET"])
def fee_category_list(request, college_id):
    categories = FeeCategory.objects.filter(college_id=college_id, is_active=True).order_by("name")
    serializer = FeeCategorySerializer(categories, many=True)
    return Response(serializer.data)
 
 
@api_view(["GET"])
def fee_structure_detail(request, pk):
    fee_structure = get_object_or_404(FeeStructure.objects.select_related("college", "department"), pk=pk)
    print(fee_structure)
    serializer = FeeStructureSerializer(fee_structure)
    return Response(serializer.data)

 
# ---------------------------------------------------------------------------
# LIST — department-wise fee structures, with a "Create Fee Structure" button
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_structure_list_page(request):
    college = _get_college(request)
    departments = Department.objects.filter(college=college).order_by("name")
    selected_department = request.GET.get("department", "").strip()
    selected_academic_year = request.GET.get("academic_year", "").strip()
    selected_year = request.GET.get("year", "").strip()
    selected_billing_cycle = request.GET.get("billing_cycle", "").strip()
    print("Before structures_qs: ")
    structures_qs = (FeeStructure.objects.filter(college=college).select_related("department","academic_year").prefetch_related("items").order_by("department__name", "-academic_year", "year"))
    
    print("After structures_qs: ",structures_qs)
    if selected_department:
        structures_qs = structures_qs.filter(department_id=selected_department)
    if selected_academic_year:
        structures_qs = structures_qs.filter(academic_year__name=selected_academic_year)
    if selected_year:
        structures_qs = structures_qs.filter(year=selected_year)
    if selected_billing_cycle:
        structures_qs = structures_qs.filter(billing_cycle=selected_billing_cycle)
    print("after id statements")
    # academic_years = (AcademicYear.objects.filter(feestructure__college=college) .order_by("-start_date").values_list("name", flat=True).distinct()) # use your real related_name
    academic_years = (FeeStructure.objects.filter(college=college).values_list("academic_year__name", flat=True).distinct().order_by("-academic_year__start_date"))
    print("after academic year")
    structures = FeeStructureListSerializer(structures_qs, many=True).data
    print(structures)
    # Group department-wise for the template (mirrors the Students page pattern).
    department_groups = OrderedDict()
    for s in structures:
        key = s["department_id"] or "none"
        if key not in department_groups:
            department_groups[key] = {"department_id": s["department_id"],"department_name": s["department_name"],"academic_year": s["academic_year"],"structures": [],}
        department_groups[key]["structures"].append(s)
        

    return render(request,"Admin/fee_structure_list.html",{"departments": departments,"academic_years": academic_years,"selected_department": selected_department,"selected_academic_year": selected_academic_year,"selected_year": selected_year,"selected_billing_cycle": selected_billing_cycle,"department_groups": list(department_groups.values()),},)
 
 
# ---------------------------------------------------------------------------
# DETAIL — clicking a row: full structure + its items + all FeeCategories
# ---------------------------------------------------------------------------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def fee_structure_detail_page(request, structure_id):
    college = _get_college(request)
    structure = get_object_or_404(FeeStructure.objects.filter(college=college).select_related("department","academic_year").prefetch_related("items__category"),id=structure_id,)
    print(structure)
    fee_categories_qs = FeeCategory.objects.filter(college=college, is_active=True).order_by("name")
    print(fee_categories_qs)
    structure_data = FeeStructureDetailSerializer(structure).data
    print(structure_data)
    fee_categories = FeeCategorySerializer(fee_categories_qs, many=True).data
    print(fee_categories)
    used_category_ids = {str(item["category"]) for item in structure_data["items"]}
    print(used_category_ids)
    missing_categories = [c for c in fee_categories if c["id"] not in used_category_ids]
    print(missing_categories)
    return render(request,"Admin/fee_structure_detail.html",{"structure": structure_data,"fee_categories": fee_categories,"missing_categories": missing_categories,},)
 

def _can_manage_fees(college_user):
    return college_user.role in ("master_admin", "office_admin", "finance_admin")

# ---------- Page ----------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_invoice_page(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return render(request, "Admin/no_access.html", status=403)
    
    others_category, _ = FeeCategory.objects.get_or_create(college=college_user.college,name="Others",defaults={"is_active": True},)

    context = {"departments": Department.objects.filter(college=college_user.college, is_active=True).order_by("name"),"others_category": others_category,"recent_batches": BulkFeeInvoiceBatch.objects.filter(college=college_user.college).select_related("category").order_by("-created_at")[:20],"can_manage_fees": True,}
    return render(request, "Admin/bulk_fee_invoices.html", context)


# ---------- Student search (for manual selection) ----------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def student_search(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "You don't have permission to search students."}, status=status.HTTP_403_FORBIDDEN)

    q = request.GET.get("q", "").strip()
    qs = StudentProfile.objects.filter(college=college_user.college, is_active=True)
    if q:
        qs = qs.filter(dj_models.Q(admission_number__icontains=q)| dj_models.Q(roll_number__icontains=q)| dj_models.Q(college_user__user__first_name__icontains=q)| dj_models.Q(college_user__user__last_name__icontains=q))
    qs = qs.select_related("college_user__user", "department").order_by("admission_number")[:20]
    return Response(StudentPreviewSerializer(qs, many=True).data)


# ---------- Preview matching students before generating ----------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_invoice_preview(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "You don't have permission to generate fee invoices."}, status=status.HTTP_403_FORBIDDEN)

    serializer = BulkInvoiceTargetSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    qs = serializer.get_queryset(college_user.college)
    count = qs.count()
    sample = qs.order_by("admission_number")[:50]

    return Response({"matched_count": count,"sample_students": StudentPreviewSerializer(sample, many=True).data,"truncated": count > 50,})


# ---------- Generate ----------
def _create_bulk_invoice_for_student(batch, student, category, data):
    already_billed = StudentFeeInvoiceItem.objects.filter(category=category,invoice__student=student,invoice__academic_year=data["academic_year"],invoice__semester=data.get("semester"),invoice__status__in=["pending", "partial", "paid", "overdue"],).exists()
    if already_billed:
        return None, False

    invoice = StudentFeeInvoice.objects.create(student=student,fee_structure=None,academic_year=data["academic_year"],semester=data.get("semester"),total_amount=data["amount_per_student"],due_date=data["due_date"],status="pending",bulk_batch=batch,)
    StudentFeeInvoiceItem.objects.create(invoice=invoice,category=category,gross_amount=data["amount_per_student"],amount=data["amount_per_student"],)
    return invoice, True


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bulk_invoice_generate(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "You don't have permission to generate fee invoices."}, status=status.HTTP_403_FORBIDDEN)

    serializer = BulkInvoiceGenerateSerializer(data=request.data, context={"college": college_user.college})
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    category = data["category"]

    students = list(serializer.get_queryset(college_user.college))
    if not students:
        return Response({"detail": "No students matched the selected criteria."}, status=status.HTTP_400_BAD_REQUEST)

    # Create the batch OUTSIDE the atomic block below, so it survives
    # even if the invoice-generation loop rolls back.
    batch = BulkFeeInvoiceBatch.objects.create(college=college_user.college,category=category,title=data["title"],remarks=data.get("remarks", ""),amount_per_student=data["amount_per_student"],academic_year=data["academic_year"],semester=data.get("semester"),target_type=data["target_type"],year_filter=data.get("year"),hostellers_only=data.get("hostellers_only", False),due_date=data["due_date"],status="pending",total_students_targeted=len(students),generated_by=request.user,)
    if data["target_type"] == "department" and data.get("department_ids"):
        batch.departments.set(data["department_ids"])

    created_count = 0
    total_amount = Decimal("0")
    failure_reason = ""

    try:
        with transaction.atomic():
            rows = []
            for student in students:
                invoice, was_created = _create_bulk_invoice_for_student(batch, student, category, data)
                rows.append(BulkFeeInvoiceBatchStudent(batch=batch,student=student,invoice=invoice,status="created" if was_created else "skipped",skip_reason="" if was_created else "Already billed for this category/period.",))
                if was_created:
                    created_count += 1
                    total_amount += data["amount_per_student"]
            BulkFeeInvoiceBatchStudent.objects.bulk_create(rows)
        batch.status = "completed"
    except Exception as exc:
        logger.exception("Bulk invoice generation failed for batch %s", batch.id)
        batch.status = "failed"
        failure_reason = str(exc)[:250]
        created_count = 0
        total_amount = Decimal("0")

    batch.total_invoices_created = created_count
    batch.total_amount = total_amount
    batch.failure_reason = failure_reason
    batch.save(update_fields=["status", "total_invoices_created", "total_amount", "failure_reason", "updated_at"])
    payload = BulkFeeInvoiceBatchSerializer(batch).data

    # ---- Failure: return an error status so the frontend shows it as a failure ----
    if batch.status == "failed":
        return Response({"detail": f"Invoice generation failed. No invoices were created. Reason: {failure_reason or 'Unknown error'}","batch": payload,},status=status.HTTP_500_INTERNAL_SERVER_ERROR,)
    # ---- Success ----
    skipped_count = len(students) - created_count
    if created_count == 0:
        message = f"No new invoices created — all {skipped_count} student(s) were already billed for this category/period."
    elif skipped_count:
        message = f"{created_count} invoice(s) created. {skipped_count} student(s) skipped (already billed)."
    else:
        message = f"{created_count} invoice(s) created successfully."
    return Response({**payload, "skipped_count": skipped_count, "message": message},status=status.HTTP_201_CREATED,)


# ---------- History / detail ----------
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_invoice_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    batches = BulkFeeInvoiceBatch.objects.filter(college=college_user.college) \
        .select_related("category").order_by("-created_at")[:100]
    return Response(BulkFeeInvoiceBatchSerializer(batches, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def bulk_invoice_detail(request, batch_id):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    batch = get_object_or_404(BulkFeeInvoiceBatch, id=batch_id, college=college_user.college)
    rows = batch.student_rows.select_related("student__college_user__user", "student__department", "invoice").order_by("student__admission_number")
    return Response({"batch": BulkFeeInvoiceBatchSerializer(batch).data,"rows": BulkFeeInvoiceBatchStudentSerializer(rows, many=True).data,})



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_history_page(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return render(request, "Admin/no_access.html", status=403)

    context = {"departments": Department.objects.filter(college=college_user.college, is_active=True).order_by("name"),}
    return render(request, "Admin/fee_payment_history.html", context)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    qs = StudentFeeInvoice.objects.filter(student__college=college_user.college).select_related("student__college_user__user", "student__department").prefetch_related("items__category").order_by("-generated_at")

    department_id = request.GET.get("department")
    if department_id:
        qs = qs.filter(student__department_id=department_id)

    year = request.GET.get("year")
    if year:
        qs = qs.filter(student__year=year)

    invoice_status = request.GET.get("status")
    if invoice_status:
        qs = qs.filter(status=invoice_status)

    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(dj_models.Q(invoice_number__icontains=search) |dj_models.Q(student__admission_number__icontains=search) |dj_models.Q(student__college_user__user__first_name__icontains=search) |dj_models.Q(student__college_user__user__last_name__icontains=search))

    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page = 1
    page_size = 25
    total_count = qs.count()
    start = (page - 1) * page_size
    page_qs = qs[start:start + page_size]

    return Response({"results": AdminInvoiceListSerializer(page_qs, many=True).data,"count": total_count,"page": page,"page_size": page_size,"has_next": start + page_size < total_count,})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def invoice_detail(request, invoice_id):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    invoice = get_object_or_404(StudentFeeInvoice.objects.select_related("student__college_user__user", "student__department").prefetch_related("items__category", "payments__collected_by"),id=invoice_id, student__college=college_user.college,)
    return Response(AdminInvoiceDetailSerializer(invoice).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invoice_record_offline_payment(request, invoice_id):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student__college=college_user.college)
    if invoice.status in ("paid", "waived", "cancelled"):
        return Response({"detail": f"This invoice is already {invoice.get_status_display()} — no further payment can be recorded."},status=status.HTTP_400_BAD_REQUEST,)

    serializer = InvoiceOfflinePaymentSerializer(data=request.data, context={"invoice": invoice})
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    with transaction.atomic():
        FeePayment.objects.create(invoice=invoice,student=invoice.student,payment_type="offline",payment_mode=d["payment_mode"],amount=d["amount"],cheque_or_dd_number=d.get("cheque_or_dd_number", ""),bank_name=d.get("bank_name", ""),collected_by=request.user,status="success" if d.get("mark_as_paid", True) else "pending",paid_at=timezone.now() if d.get("mark_as_paid", True) else None,remarks=d.get("remarks", ""),)
        if d.get("mark_as_paid", True):
            invoice.refresh_status()

    invoice.refresh_from_db()
    return Response(AdminInvoiceDetailSerializer(invoice).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invoice_override_status(request, invoice_id):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    invoice = get_object_or_404(StudentFeeInvoice, id=invoice_id, student__college=college_user.college)

    serializer = InvoiceStatusOverrideSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    d = serializer.validated_data

    invoice.status = d["status"]
    if d.get("reason"):
        invoice.discount_reason = d["reason"]  # or a dedicated status_reason field if you want to keep discount_reason separate
    invoice.save(update_fields=["status", "discount_reason", "updated_at"])

    return Response(AdminInvoiceDetailSerializer(invoice).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def offline_collection_history_page(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return render(request, "Admin/no_access.html", status=403)

    collectors = User.objects.filter(fee_payments_collected__student__college=college_user.college,fee_payments_collected__payment_type="offline",).distinct().order_by("first_name")

    context = {"departments": Department.objects.filter(college=college_user.college, is_active=True).order_by("name"),"collectors": collectors,}
    return render(request, "Admin/offline_collection_history.html", context)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def offline_collection_list(request):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    qs = FeePayment.objects.filter(student__college=college_user.college, payment_type="offline").select_related("student__college_user__user", "student__department", "invoice", "collected_by").order_by("-created_at")

    department_id = request.GET.get("department")
    if department_id:
        qs = qs.filter(student__department_id=department_id)

    year = request.GET.get("year")
    if year:
        qs = qs.filter(student__year=year)

    payment_mode = request.GET.get("payment_mode")
    if payment_mode:
        qs = qs.filter(payment_mode=payment_mode)

    payment_status = request.GET.get("status")
    if payment_status:
        qs = qs.filter(status=payment_status)

    collected_by = request.GET.get("collected_by")
    if collected_by:
        qs = qs.filter(collected_by_id=collected_by)

    date_from = request.GET.get("date_from")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = request.GET.get("date_to")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(dj_models.Q(receipt_number__icontains=search) |dj_models.Q(student__admission_number__icontains=search) |dj_models.Q(invoice__invoice_number__icontains=search) |dj_models.Q(student__college_user__user__first_name__icontains=search) |dj_models.Q(student__college_user__user__last_name__icontains=search) |dj_models.Q(cheque_or_dd_number__icontains=search))

    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page = 1
    page_size = 25
    total_count = qs.count()
    start = (page - 1) * page_size
    page_qs = qs[start:start + page_size]

    summary = qs.aggregate(total_collected=Sum("amount", filter=dj_models.Q(status="success")),pending_count=Count("id", filter=dj_models.Q(status="pending")),)

    return Response({"results": OfflineCollectionSerializer(page_qs, many=True).data,"count": total_count,"page": page,"page_size": page_size,"has_next": start + page_size < total_count,"total_collected": summary["total_collected"] or 0,"pending_count": summary["pending_count"] or 0,})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def mark_offline_payment_cleared(request, payment_id):
    college_user = CollegeUser.objects.get(user=request.user)
    if not _can_manage_fees(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    payment = get_object_or_404(FeePayment, id=payment_id, student__college=college_user.college, payment_type="offline")
    if payment.status != "pending":
        return Response({"detail": "Only a pending offline payment can be marked cleared."}, status=status.HTTP_400_BAD_REQUEST)

    serializer = MarkOfflinePaymentClearedSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        payment.status = "success"
        payment.paid_at = timezone.now()
        if serializer.validated_data.get("remarks"):
            payment.remarks = (payment.remarks + " | " if payment.remarks else "") + serializer.validated_data["remarks"]
        payment.save(update_fields=["status", "paid_at", "remarks", "updated_at"])
        payment.invoice.refresh_status()

    return Response(OfflineCollectionSerializer(payment).data)


def _can_manage_enrollment(college_user):
    return college_user.role in ("master_admin", "office_admin")


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enroll_students_page(request):
    college_user = _get_college_user(request)
    if not _can_manage_enrollment(college_user):
        return render(request, "Admin/no_access.html", status=403)
    college = college_user.college
    context = {
        "departments": Department.objects.filter(college=college, is_active=True).order_by("name"),
        "academic_years": AcademicYear.objects.filter(college=college),
        "current_academic_year": AcademicYear.objects.filter(college=college, is_current=True).first(),
    }
    return render(request, "Admin/enroll_students.html", context)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enrollment_classrooms(request):
    college_user = _get_college_user(request)
    if not _can_manage_enrollment(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    qs = Classroom.objects.filter(college=college_user.college)
    for param, field in (("academic_year", "academic_year_id"), ("department", "department_id"),
                         ("year", "year"), ("semester", "semester")):
        value = request.GET.get(param)
        if value:
            qs = qs.filter(**{field: value})
    qs = qs.annotate(student_count=Count("enrollments", filter=Q(enrollments__is_active=True))).order_by("section")
    return Response([{"id": str(c.id), "name": c.name, "section": c.section,
                      "room_number": c.room_number, "student_count": c.student_count} for c in qs])


def _eligible_students(classroom):
    return (StudentProfile.objects.filter(
        college_id=classroom.college_id, is_active=True, status="active",
        department_id=classroom.department_id, year=classroom.year, semester=classroom.semester,
    ).select_related("college_user__user").order_by("roll_number", "admission_number"))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def enrollment_students(request):
    college_user = _get_college_user(request)
    if not _can_manage_enrollment(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    classroom = _get_object_or_404_uuid(Classroom, id=request.GET.get("classroom"), college=college_user.college)

    enrolled_here = set(StudentEnrollment.objects.filter(classroom=classroom, is_active=True)
                        .values_list("student_id", flat=True))
    elsewhere = dict(StudentEnrollment.objects.filter(
        classroom__academic_year_id=classroom.academic_year_id,
        classroom__semester=classroom.semester,
        is_active=True,
    ).exclude(classroom=classroom).values_list("student_id", "classroom__name"))

    rows = []
    for s in _eligible_students(classroom):
        u = s.college_user.user
        rows.append({
            "id": str(s.id),
            "name": f"{u.first_name} {u.last_name}".strip() or u.email,
            "admission_number": s.admission_number,
            "roll_number": s.roll_number,
            "section": s.section,
            "enrolled_here": s.id in enrolled_here,
            "enrolled_elsewhere": elsewhere.get(s.id),
        })
    return Response({"classroom": {"id": str(classroom.id), "name": classroom.name}, "students": rows})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def enrollment_save(request):
    college_user = _get_college_user(request)
    if not _can_manage_enrollment(college_user):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    classroom = _get_object_or_404_uuid(Classroom, id=request.data.get("classroom"), college=college_user.college)
    if not classroom.is_active:
        return Response({"detail": "This classroom is closed."}, status=status.HTTP_400_BAD_REQUEST)
    if classroom.academic_year_id is None or not classroom.academic_year.is_current:
        return Response({"detail": "Students can only be enrolled into a classroom of the current academic year."},
                        status=status.HTTP_400_BAD_REQUEST)

    ids = list({str(i) for i in request.data.get("student_ids", [])})
    if not ids:
        return Response({"detail": "Select at least one student."}, status=status.HTTP_400_BAD_REQUEST)

    students = list(_eligible_students(classroom).filter(id__in=ids))
    if len(students) != len(ids):
        return Response({"detail": "Some selected students don't match this classroom's department, year and semester."},
                        status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        for s in students:
            enroll_student(s, classroom)
    return Response({"message": f"{len(students)} student(s) enrolled in {classroom.name}.", "enrolled_count": len(students)})


