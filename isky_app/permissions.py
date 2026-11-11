from django.db.models import Q
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import CollegeUser,User

class AuthRedirect(APIException):
    status_code = 401
    default_detail = "Authentication required."
    default_code = "auth_redirect"

class IsMasterOrOfficeAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Access user role (adjust path based on where role is defined on your User/CollegeUser model)
        return request.user.college_memberships.filter(role__in=['master_admin', 'office_admin'],status='active').exists()
    
class IsMasterAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.college_memberships.filter(Q(role='master_admin') | Q(role='office_admin'),status='active').exists()

class IsAuthenticated(BasePermission):
    def has_permission(self, request, view):
        access_token = request.session.get("access_token")
        if not access_token:
            return self._fail(request, "Your session has expired. Please log in again.")

        try:
            token = AccessToken(access_token)
            user = User.objects.get(id=token["user_id"])
        except TokenError:
            return self._fail(request, "Your session has expired. Please log in again.")
        except User.DoesNotExist:
            return self._fail(request, "User does not exist.")
        except Exception:
            return self._fail(request, "Authentication failed. Please log in again.")

        if not user.is_active or user.status != "active":
            return self._fail(request, "Your account is inactive.")

        request.user = user
        return True

    def _fail(self, request, message):
        request.session.flush()
        raise AuthRedirect(detail=message) 

# ---------------------------------------------------------------------------
# Roles (CollegeUser.role)
# ---------------------------------------------------------------------------
MASTER_ADMIN = "master_admin"
OFFICE_ADMIN = "office_admin"
FINANCE_ADMIN = "finance_admin"
STAFF_ADMIN = "staff_admin"

ALL_ADMIN_ROLES = {MASTER_ADMIN, OFFICE_ADMIN, FINANCE_ADMIN, STAFF_ADMIN}

# Staff sub-roles (StaffProfile.staff_role) — only meaningful when
# role == STAFF_ADMIN.
HOD = "hod"
CLASS_ADVISOR = "class_advisor"
STAFF = "staff"


# ---------------------------------------------------------------------------
# Resolving "who is this request, as a CollegeUser"
# ---------------------------------------------------------------------------
def get_college_user(request):
   
    college_user = getattr(request, "college_user", None)
    if college_user is not None:
        return college_user

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    return user.college_memberships.select_related("staff_profile", "staff_profile__department").first()


def get_user_role(request):
    college_user = get_college_user(request)
    return college_user.role if college_user else None

FORM_ROLE_TO_STAFF_ROLE = {
    "hod": "hod",
    "faculty_advisor": "class_advisor","staff":"staff"
}

def _role_matches(form_role, actual_role):
    if form_role in FORM_ROLE_TO_STAFF_ROLE:
        return actual_role == FORM_ROLE_TO_STAFF_ROLE[form_role]
    if form_role == "staff":
        # generic "Staff" tab: any role that isn't HOD / advisor
        return actual_role is not None and actual_role not in FORM_ROLE_TO_STAFF_ROLE.values()
    return False


def get_staff_role(request):
    college_user = get_college_user(request)
    if college_user is None:
        return None
    staff_profile = getattr(college_user, "staff_profile", None)
    return staff_profile.staff_role if staff_profile else None


def get_staff_department_id(request):
    college_user = get_college_user(request)
    staff_profile = getattr(college_user, "staff_profile", None) if college_user else None
    return staff_profile.department_id if staff_profile else None


def get_advisor_year(request):
   
    college_user = get_college_user(request)
    staff_profile = getattr(college_user, "staff_profile", None) if college_user else None
    return staff_profile.advisor_year if staff_profile else None


# ---------------------------------------------------------------------------
# Nav-item -> visible or not, per role (+ staff sub-role).
#
# Keys match (or extend) the sidebar's `active_nav` values. fees is split
# into its four real pages instead of one shared "fees" flag, since
# finance_admin, office_admin and staff_admin each need different subsets
# of Fee Management.
# ---------------------------------------------------------------------------
NAV_KEYS = [
    "dashboard", "students", "departments", "subjects",
    "office_admins", "staff_admins", "classrooms", "timetable",
    "attendance", "promotion",
    "fee_structure", "assign_fee_structure", "fee_transactions", "settlement_batches",
    "settings",
]


def nav_access(role, staff_role=None):
    print(staff_role)
    access = {key: False for key in NAV_KEYS}
    print(role)
    if role == MASTER_ADMIN:
        return {key: True for key in NAV_KEYS}

    if role == OFFICE_ADMIN:
        # excluded: fee_structure, assign_fee_structure, fee_transactions,
        # settlement_batches, attendance, subjects
        access.update({"dashboard": True,"students": True,"departments": True,"office_admins": True,"staff_admins": True,"classrooms": True,"timetable": True,"promotion": True,"settings": True,})
        return access

    if role == FINANCE_ADMIN:
        access.update({"dashboard": True,"students": True,"fee_structure": True,"assign_fee_structure": True,"fee_transactions": True,"settlement_batches": True,})  # read-only — see can_edit_students()
        return access

    if role == STAFF_ADMIN:
        access["dashboard"] = True
        if staff_role == HOD:
            access.update({"students": True,     "attendance": True,"timetable": True,"classrooms": True,   "subjects": True,   })  # add + assign subjects# assigning staff to classrooms# own department only — scope in the view
        elif staff_role == CLASS_ADVISOR:
            access.update({"students": True,  "attendance": True,"timetable": True,"classrooms": True,   "subjects": True})   # own class only — scope in the view
        elif staff_role == STAFF:
            access.update({"attendance": True, "timetable": True,"classrooms": True,   "subjects": True})  # own subjects only — scope in the view
        # No matching StaffProfile yet -> only "dashboard" stays visible.

        return access

    return access  # unknown/no role -> nothing


def can_edit_students(role):
    """finance_admin sees student data but can't edit it."""
    return role != FINANCE_ADMIN


def sidebar_permissions(request):
    role = get_user_role(request)
    staff_role = get_staff_role(request) if role == STAFF_ADMIN else None
    return {
        "nav_access": nav_access(role, staff_role),
        "user_role": role,
        "staff_role": staff_role,
        "can_edit_students": can_edit_students(role),
    }
    



# ---------------------------------------------------------------------------
# View-level enforcement — hiding a sidebar link doesn't stop someone
# hitting the URL directly, so gate the view itself too.
# ---------------------------------------------------------------------------
def role_required(*allowed_roles, redirect_to=None):
    allowed = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            role = get_user_role(request)
            if role not in allowed:
                if redirect_to:
                    return redirect(redirect_to)
                raise PermissionDenied("You don't have access to this page.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def staff_role_required(*allowed_staff_roles, redirect_to=None):
    allowed = set(allowed_staff_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            role = get_user_role(request)
            staff_role = get_staff_role(request)
            if role != STAFF_ADMIN or staff_role not in allowed:
                if redirect_to:
                    return redirect(redirect_to)
                raise PermissionDenied("You don't have access to this page.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


# Convenience shortcuts
master_admin_only = role_required(MASTER_ADMIN)
master_or_office_admin = role_required(MASTER_ADMIN, OFFICE_ADMIN)
master_or_finance_admin = role_required(MASTER_ADMIN, FINANCE_ADMIN)
def master_or_staff_role(*allowed_staff_roles, redirect_to=None):
   
    allowed = set(allowed_staff_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            role = get_user_role(request)
            if role == MASTER_ADMIN:
                return view_func(request, *args, **kwargs)
            if role == STAFF_ADMIN and get_staff_role(request) in allowed:
                return view_func(request, *args, **kwargs)
            if redirect_to:
                return redirect(redirect_to)
            raise PermissionDenied("You don't have access to this page.")
        return wrapped
    return decorator


hod_only = master_or_staff_role(HOD)
advisor_only = master_or_staff_role(CLASS_ADVISOR)
staff_only = master_or_staff_role(STAFF)


# ---------------------------------------------------------------------------
# Queryset scoping helpers — the actual "own department / own class / own
# subject" enforcement. Nav flags only control link visibility; call these
# inside the view so a HOD can't just edit the URL to see another
# department's students.
# ---------------------------------------------------------------------------
def scope_students_queryset(request, queryset):
    
    role = get_user_role(request)

    if role in (MASTER_ADMIN, OFFICE_ADMIN, FINANCE_ADMIN):
        return queryset  # finance_admin is read-only in the UI, not query-scoped

    if role == STAFF_ADMIN:
        staff_role = get_staff_role(request)
        dept_id = get_staff_department_id(request)

        if staff_role == HOD:
            return queryset.filter(department_id=dept_id)

        if staff_role == CLASS_ADVISOR:
            year = get_advisor_year(request)
            return queryset.filter(department_id=dept_id, year=year)

        # plain "staff" role has no student-list access at all
        return queryset.none()

    return queryset.none()


def scope_timetable_slots_queryset(request, queryset):
    role = get_user_role(request)

    if role in (MASTER_ADMIN, OFFICE_ADMIN):
        return queryset

    if role == STAFF_ADMIN:
        staff_role = get_staff_role(request)
        dept_id = get_staff_department_id(request)

        if staff_role == HOD:
            return queryset.filter(classroom__department_id=dept_id)

        if staff_role == CLASS_ADVISOR:
            year = get_advisor_year(request)
            return queryset.filter(classroom__department_id=dept_id, classroom__year=year)

        if staff_role == STAFF:
            return queryset.filter(teacher=request.user)

    return queryset.none()