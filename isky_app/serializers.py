from datetime import date
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.contrib.auth import authenticate, get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers
from django.contrib.auth.hashers import make_password,check_password

from .helper import EnrollmentConflict, classroom_is_open, enroll_student, get_or_create_classroom, resolve_target_academic_year
from .models import SEMESTER_CHOICES, AcademicYear, BulkFeeInvoiceBatch, BulkFeeInvoiceBatchStudent, Classroom, College, CollegeUser, Department, DepartmentSubjectMapping, FeeCategory, FeeConcession, FeePayment, FeeStructure, FeeStructureItem, PaymentGatewayLink, PeriodAttendanceSession, StaffProfile, StudentAttendance, StudentEnrollment, StudentFeeInvoice, StudentFeeInvoiceItem, StudentProfile, Subject, TimetableSlot,User
from django.contrib.auth.password_validation import validate_password
from django.utils.crypto import get_random_string
from rest_framework.exceptions import PermissionDenied
import re,string


BLOOD_GROUP_CHOICES = [("A+", "A+"),("A-", "A-"),("B+", "B+"),("B-", "B-"),("O+", "O+"),("O-", "O-"),("AB+", "AB+"),("AB-", "AB-"),]
YEAR_CHOICES = [(1, '1st Year'), (2, '2nd Year'), (3, '3rd Year'), (4, '4th Year')]


# -------------------------------------------------------------------
# 1. Platform Admin Creation Serializer
# -------------------------------------------------------------------
class CreatePlatformUserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id","email","password","first_name","last_name","mobile_number","status","created_at"]
        read_only_fields = ["id", "status", "created_at"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        email = validated_data.pop("email")
        
        # Explicitly set user_type to platform_admin
        user = User.objects.create_user(username=email,email=email,password=password,user_type="platform_admin",status="active",is_staff=True,is_superuser=True,**validated_data) # Gives admin access   # Platform level super admin permissions
        return user


# -------------------------------------------------------------------
# 2. Platform Admin Login Serializer
# -------------------------------------------------------------------
class PlatformUserLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")
        

        if not email or not password:
            raise serializers.ValidationError("Both email and password are required.")
        
        user = User.objects.filter(email=email).first()

        if not user:
            raise serializers.ValidationError("User not found.")
        
        if not check_password(password, user.password):
            raise serializers.ValidationError("Invalid email or password.")

        if user.user_type != "platform_admin":
            raise serializers.ValidationError("Access denied. Not a platform admin account.")

        if user.status != "active":
            raise serializers.ValidationError("User account is inactive, suspended, or blocked.")

        attrs["user"] = user
        return attrs



 
class CollegeSerializer(serializers.ModelSerializer):
    class Meta:
        model = College
        fields = ["id", "name", "code", "email", "mobile_number", "address", "city","state", "country", "pincode", "status", "is_active","created_at", "updated_at",]
        read_only_fields = ["id", "created_at", "updated_at"]
 
    def validate_code(self, value):
        return value.strip().upper()
 
 
class CollegeUserListSerializer(serializers.ModelSerializer):
    """Shape the platform pages read: one row per college membership."""
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="user.email", read_only=True)
    mobile_number = serializers.CharField(source="user.mobile_number", read_only=True)
    college_name = serializers.CharField(source="college.name", read_only=True)
    is_active = serializers.SerializerMethodField()
 
    class Meta:
        model = CollegeUser
        fields = ["id", "full_name", "email", "mobile_number", "college", "college_name","role", "status", "is_active", "employee_or_student_id", "created_at",]
 
    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.email
 
    def get_is_active(self, obj):
        return obj.status == "active"
 
 
class CollegeUserCreateSerializer(serializers.Serializer):
    """Creates the login (User) and its college membership (CollegeUser) together."""
    college = serializers.PrimaryKeyRelatedField(queryset=College.objects.all())
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    role = serializers.ChoiceField(choices=[r for r in CollegeUser.ROLE_CHOICES if r[0] != "student"])
    employee_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    password = serializers.CharField(write_only=True, min_length=8)
 
    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
 
    def validate_phone(self, value):
        value = value.strip()
        if value and User.objects.filter(mobile_number=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value
 
    def validate_college(self, college):
        if college.status != "active" or not college.is_active:
            raise serializers.ValidationError("This college is not active.")
        return college
 
    def validate(self, attrs):
        validate_password(attrs["password"])  # Django's configured password rules
        return attrs
 
    @transaction.atomic
    def create(self, validated_data):
        user = User.objects.create_user(username=validated_data["email"],email=validated_data["email"],password=validated_data["password"],first_name=validated_data["first_name"],last_name=validated_data.get("last_name", ""),mobile_number=validated_data.get("phone") or None, user_type="college_user",password_updated=False,  ) # unique + nullable # force a password change on first sign-in
        return CollegeUser.objects.create(user=user,college=validated_data["college"],role=validated_data["role"],employee_or_student_id=validated_data.get("employee_id", ""),)

# -------------------------------------------------------------------
# 1. College Serializers
# -------------------------------------------------------------------
class CollegeSerializer(serializers.ModelSerializer):
    class Meta:
        model = College
        fields = ["id","name","code","email","mobile_number","address","city","state","country","pincode","status","is_active","created_at","updated_at",]
        read_only_fields = ["id", "created_at", "updated_at"]


# -------------------------------------------------------------------
# 2. College Admin Creation Serializer
# -------------------------------------------------------------------
class CreateCollegeAdminSerializer(serializers.Serializer):
    # College reference
    college_id = serializers.UUIDField(write_only=True)
    
    # User Credentials & Info
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    mobile_number = serializers.CharField(max_length=16, required=False, allow_null=True)
    
    
    # CollegeUser membership specs
    role = serializers.ChoiceField(choices=CollegeUser.ROLE_CHOICES,default="master_admin")
    employee_or_student_id = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def validate_college_id(self, value):
        if not College.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("College does not exist or is inactive.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def create(self, validated_data):
        college_id = validated_data.pop("college_id")
        password = validated_data.pop("password")
        role = validated_data.pop("role")
        employee_or_student_id = validated_data.get("employee_or_student_id", "")
        college = College.objects.get(id=college_id)

        # Atomic transaction to ensure both records create safely together
        with transaction.atomic():
            # Create Custom User
            user = User.objects.create_user(username=validated_data["email"],email=validated_data["email"],password=password,first_name=validated_data.get("first_name", ""),last_name=validated_data.get("last_name", ""),mobile_number=validated_data.get("mobile_number"),user_type="college_user",status="active")  # Uses email as username
            # Assign to College as Admin/Member
            college_user = CollegeUser.objects.create(user=user,college=college,role=role,status="active",employee_or_student_id=employee_or_student_id)

        return {
            "user_id": str(user.id),
            "email": user.email,
            "college_id": str(college.id),
            "college_name": college.name,
            "role": college_user.role,
            "employee_or_student_id": college_user.employee_or_student_id
        }
        
# Staff Profile
class StaffProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffProfile
        fields = ['id','college_user','department','staff_role','designation','joining_date','is_active','created_at','updated_at',]
        read_only_fields = ['id', 'created_at', 'updated_at']
        

# Department
class DepartmentListSerializer(serializers.ListSerializer):
    def validate(self, attrs):
        codes = [item['code'] for item in attrs]
        dupes = {c for c in codes if codes.count(c) > 1}
        if dupes:
            raise serializers.ValidationError(
                f"Duplicate codes in this batch: {', '.join(dupes)}"
            )
        return attrs


class DepartmentSerializer(serializers.ModelSerializer):
    college_name = serializers.ReadOnlyField(source='college.name')
    staff_count = serializers.IntegerField(read_only=True)
    student_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ['id', 'college', 'college_name','short_name',"degree", 'name', 'code', 'is_active','staff_count', 'student_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
        list_serializer_class = DepartmentListSerializer

    def validate_code(self, value):
        cleaned = str(value).strip().upper()
        if Department.objects.filter(code=cleaned).exists():
            raise serializers.ValidationError("A department with this code already exists.")
        return cleaned
    
    def validate_short_name(self, value):
        return value.strip() if value else value

    def validate_name(self, value):
        cleaned = value.strip()
        if not cleaned:
            raise serializers.ValidationError("Name cannot be empty.")
        return cleaned
    
    
# Create Office Admin
class OfficeAdminCreateSerializer(serializers.ModelSerializer):
    # Additional User fields needed to create the user account
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    mobile_number = serializers.CharField(write_only=True, required=False, allow_null=True)
    

    class Meta:
        model = CollegeUser
        fields = ['id','college','email','first_name','last_name','department','mobile_number','employee_or_student_id','status','created_at']
        read_only_fields = ['id', 'created_at']

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_mobile_number(self, value):
        if User.objects.filter(mobile_number=value).exists():
            raise serializers.ValidationError("A user with this mobile number already exists.")
        return value
    

    def create(self, validated_data):
        # Extract user data
        email = validated_data.pop('email')
        first_name = validated_data.pop('first_name', '')
        last_name = validated_data.pop('last_name', '')
        mobile_number = validated_data.pop('mobile_number', None)
        college = validated_data.pop('college')
        employee_id = validated_data.pop('employee_or_student_id', '')
        department = validated_data.pop('department')
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        generated_password = get_random_string(length=10, allowed_chars=chars)
        with transaction.atomic():
            # 1. Create User account
            user = User.objects.create_user(username=email, email=email,password=generated_password,first_name=first_name,last_name=last_name,mobile_number=mobile_number,user_type="college_user") # Using email as username
            # 2. Create CollegeUser linking user to college as 'office_admin'
            college_user = CollegeUser.objects.create(user=user,college=college,department=department,role='office_admin',employee_or_student_id=employee_id,**validated_data)  # Hardcode role to office_admin
            college_user.generated_password = generated_password
            return college_user
        
        
DEPARTMENT_SPECIAL_OPTIONS = ("All", "No Access") 
class OfficeAdminUpdateSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="user.first_name", max_length=150)
    last_name = serializers.CharField(source="user.last_name", max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(source="user.email")
    mobile_number = serializers.CharField(
        source="user.mobile_number", max_length=16, required=False, allow_blank=True, allow_null=True
    )
    send_password = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = CollegeUser
        fields = ["status", "department", "role", "first_name", "last_name", "email", "mobile_number","send_password"]

    def validate_role(self, value):
        valid_roles = dict(CollegeUser.ROLE_CHOICES)
        if value not in valid_roles:
            raise serializers.ValidationError("Invalid role.")
        return value
    
    def validate_department(self, value):
        value = (value or "").strip()
        if value in DEPARTMENT_SPECIAL_OPTIONS:
            return value
        exists = Department.objects.filter(is_active=True,college=self.instance.college,name=value,).exists()
        if not exists:
            raise serializers.ValidationError("Invalid department.")
        return value

    def validate_status(self, value):
        valid_statuses = dict(CollegeUser.STATUS_CHOICES)
        if value not in valid_statuses:
            raise serializers.ValidationError("Invalid status.")
        return value

    def validate_email(self, value):
        qs = User.objects.filter(email__iexact=value).exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate_mobile_number(self, value):
        if value:
            qs = User.objects.filter(mobile_number=value).exclude(pk=self.instance.user_id)
            if qs.exists():
                raise serializers.ValidationError("This mobile number is already in use.")
        return value

    def update(self, instance, validated_data):
        validated_data.pop("send_password", None)
        user_data = validated_data.pop("user", {})
        if user_data:
            user = instance.user
            if "email" in user_data:
                user_data["username"] = user_data["email"]  # keep login in sync
            for attr, val in user_data.items():
                setattr(user, attr, val)
            user.save(update_fields=list(user_data.keys()))

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance
    


#Create staff serializers
class StaffCreateSerializer(serializers.ModelSerializer):
    # ---- User fields (not on StaffProfile, so declared explicitly) ----
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    mobile_number = serializers.CharField(write_only=True, required=False, allow_null=True)
 
    # ---- CollegeUser fields ----
    college = serializers.PrimaryKeyRelatedField(queryset=College.objects.all(), write_only=True)
    employee_or_student_id = serializers.CharField(write_only=True, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False,allow_null=True)
    blood_group = serializers.ChoiceField(source="college_user.blood_group",choices=BLOOD_GROUP_CHOICES,required=False,allow_null=True,allow_blank=True)
    emergency_contact_number = serializers.CharField(source="college_user.emergency_contact_number",required=False,allow_null=True,allow_blank=True,max_length=16)
    address = serializers.CharField(source="college_user.address",required=False,allow_null=True,allow_blank=True)
    work_experience = serializers.CharField(source="college_user.work_experience",required=False,allow_blank=True,max_length=150)
 
    # ---- StaffProfile fields (override to attach validation) ----
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    staff_role = serializers.ChoiceField(choices=StaffProfile.STAFF_ROLE_CHOICES)
    designation = serializers.CharField(required=False, allow_blank=True)
    joining_date = serializers.DateField(required=False, allow_null=True)
    advisor_year = serializers.ChoiceField(choices=YEAR_CHOICES, required=False, allow_null=True, allow_blank=True)
 
    class Meta:
        model = StaffProfile
        fields = ["id","college","email","first_name","last_name","mobile_number","employee_or_student_id","date_of_birth","blood_group","emergency_contact_number","address","work_experience","department","staff_role","advisor_year","designation","joining_date","is_active","created_at",]
        read_only_fields = ["id", "created_at"]
 
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_mobile_number(self, value):
        if User.objects.filter(mobile_number=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value
 
    def validate(self, attrs):
        # Only one *active* HOD per department.
        role = attrs.get("staff_role")
        department = attrs.get("department")
        year = attrs.get("advisor_year") or None   # turns "" into None
        if role == "hod":
            if StaffProfile.objects.filter(department=department, staff_role="hod", is_active=True).exists():
                raise serializers.ValidationError({"staff_role": f"{department.name} already has an active HOD."})

        if role == "class_advisor":
            if year is None:
                raise serializers.ValidationError({"advisor_year": "Select the year this class advisor is responsible for."})
            if StaffProfile.objects.filter(department=department, advisor_year=year,staff_role="class_advisor", is_active=True,).exists():
                raise serializers.ValidationError({"advisor_year": f"{department.name} already has an active class advisor for this year."})
        else:
            year = None   # non-advisors never carry an advisor year

        attrs["advisor_year"] = year
        return attrs
 
    def create(self, validated_data):
        if validated_data.get("is_active") is not True:
            validated_data["is_active"] = True
        email = validated_data.pop("email")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        mobile_number = validated_data.pop("mobile_number", None)
        college = validated_data.pop("college")
        employee_id = validated_data.pop("employee_or_student_id", "")
        date_of_birth = validated_data.pop("date_of_birth", None)
        college_user_extra = validated_data.pop("college_user", {})  # blood_group, emergency_contact_number, address, work_experience
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        generated_password = get_random_string(length=10, allowed_chars=chars)
 
        with transaction.atomic():
            # 1. User account
            user = User.objects.create_user(username=email,email=email,password=generated_password,first_name=first_name,last_name=last_name,mobile_number=mobile_number,user_type="college_user",)
            # 2. CollegeUser — membership, hard-coded role
            college_user = CollegeUser.objects.create(user=user,college=college,role="staff_admin",employee_or_student_id=employee_id,date_of_birth=date_of_birth,**college_user_extra,)
            # 3. StaffProfile — department + staff_role + the rest
            staff_profile = StaffProfile.objects.create(college_user=college_user,**validated_data, ) # department, staff_role, designation, joining_date, is_active
            staff_profile.generated_password = generated_password
        return staff_profile
 
#Create bulk staff serializers
class BulkStaffUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        if not value.name.endswith('.xlsx'):
            raise serializers.ValidationError("File must be an .xlsx extension")
        return value
    
    
# Staff list
class StaffListSerializer(serializers.ModelSerializer):
 
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    employee_id = serializers.CharField(source="college_user.employee_or_student_id", read_only=True)
    status = serializers.CharField(source="college_user.status", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    date_of_birth = serializers.DateField(source="college_user.date_of_birth",read_only=True)
    blood_group = serializers.CharField(source="college_user.blood_group",read_only=True)
    emergency_contact_number = serializers.CharField(source="college_user.emergency_contact_number",read_only=True)
    address = serializers.CharField(source="college_user.address",read_only=True)
    work_experience = serializers.CharField(source="college_user.work_experience",read_only=True)
    staff_role_display = serializers.CharField(source="get_staff_role_display", read_only=True)
 
    class Meta:
        model = StaffProfile
        fields = ["id","name","email","employee_id","department_name","staff_role","staff_role_display","designation","status","is_active","date_of_birth","blood_group","emergency_contact_number","address","work_experience",]
 
    def get_name(self, obj):
        user = obj.college_user.user
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.email
    

    
class StaffUpdateSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="college_user.user.first_name", max_length=150)
    last_name = serializers.CharField(source="college_user.user.last_name", max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(source="college_user.user.email")
    mobile_number = serializers.CharField(
        source="college_user.user.mobile_number", max_length=16, required=False, allow_blank=True, allow_null=True
    )
    send_password = serializers.BooleanField(write_only=True, required=False, default=False)
    status = serializers.ChoiceField(source="college_user.status", choices=CollegeUser.STATUS_CHOICES, required=False)
    date_of_birth = serializers.DateField(source="college_user.date_of_birth",required=False,allow_null=True)
    blood_group = serializers.ChoiceField(source="college_user.blood_group",choices=BLOOD_GROUP_CHOICES,required=False,allow_blank=True,allow_null=True)
    emergency_contact_number = serializers.CharField(source="college_user.emergency_contact_number",max_length=16,required=False,allow_blank=True,allow_null=True)
    address = serializers.CharField(source="college_user.address",required=False,allow_blank=True,allow_null=True)
    work_experience = serializers.CharField(source="college_user.work_experience",max_length=150,required=False,allow_blank=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    advisor_year = serializers.ChoiceField(choices=YEAR_CHOICES, required=False, allow_null=True)

    class Meta:
        model = StaffProfile
        fields = [
            "staff_role", "designation", "department", "advisor_year", "is_active",
            "first_name", "last_name", "email", "mobile_number", "status","date_of_birth","address", "blood_group","work_experience", "emergency_contact_number","send_password"
        ]

    def validate_staff_role(self, value):
        if value not in dict(StaffProfile.STAFF_ROLE_CHOICES):
            raise serializers.ValidationError("Invalid staff role.")
        return value

    def validate_email(self, value):
        qs = User.objects.filter(email__iexact=value).exclude(pk=self.instance.college_user.user_id)
        if qs.exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate_mobile_number(self, value):
        if value:
            qs = User.objects.filter(mobile_number=value).exclude(pk=self.instance.college_user.user_id)
            if qs.exists():
                raise serializers.ValidationError("This mobile number is already in use.")
        return value

    def validate(self, attrs):
        # Resolve the effective role/year/department after this partial update is applied,
        # so we can enforce the class_advisor <-> advisor_year relationship correctly.
        effective_role = attrs.get("staff_role", self.instance.staff_role)
        effective_year = attrs.get("advisor_year", self.instance.advisor_year)
        effective_department = attrs.get("department", self.instance.department)

        if effective_role == "class_advisor":
            if effective_year is None:
                raise serializers.ValidationError({"advisor_year": "Select a year for the class advisor."})
            if effective_department is None:
                raise serializers.ValidationError({"department": "Assign a department before setting a class advisor year."})

            conflict = StaffProfile.objects.filter(
                department=effective_department,
                advisor_year=effective_year,
                staff_role="class_advisor",
                is_active=True,
            ).exclude(pk=self.instance.pk)
            if conflict.exists():
                raise serializers.ValidationError({
                    "advisor_year": "Another active staff member is already the class advisor for this department and year."
                })
        else:
            # Non-advisors shouldn't carry a stale advisor_year
            attrs["advisor_year"] = None

        return attrs

    def update(self, instance, validated_data):
        validated_data.pop("send_password", None)
        college_user_data = validated_data.pop("college_user", {})
        user_data = college_user_data.pop("user", {}) if college_user_data else {}

        if user_data:
            user = instance.college_user.user
            if "email" in user_data:
                user_data["username"] = user_data["email"]
            for attr, val in user_data.items():
                setattr(user, attr, val)
            user.save(update_fields=list(user_data.keys()))

        if college_user_data:
            college_user = instance.college_user
            for attr, val in college_user_data.items():
                setattr(college_user, attr, val)
            college_user.save(update_fields=list(college_user_data.keys()))

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance


# Departments subject maping

class DepartmentSubjectMappingSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.short_name", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    teacher_name = serializers.CharField(source="teacher.college_user.user.get_full_name", read_only=True)

    class Meta:
        model = DepartmentSubjectMapping
        fields = ["department", "department_name", "year", "year_display", "semester", "semester_display","teacher","teacher_name"]

    def validate(self, attrs):
        print("mapping validate")
        year = attrs.get("year")
        semester = attrs.get("semester")
        if year and semester:
            valid_semesters = {2 * year - 1, 2 * year}
            if semester not in valid_semesters:
                raise serializers.ValidationError({"semester": f"Year {year} only allows semesters {sorted(valid_semesters)}."})
        return attrs
    
class DepartmentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["name", "code", "short_name", "is_active"]

    def validate_code(self, value):
        qs = Department.objects.filter(college=self.instance.college, code=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another department in this college already uses this code.")
        return value


class StaffListItemSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="college_user.user.first_name", read_only=True)
    last_name = serializers.CharField(source="college_user.user.last_name", read_only=True)
    email = serializers.CharField(source="college_user.user.email", read_only=True)
    staff_role_display = serializers.CharField(source="get_staff_role_display", read_only=True)

    class Meta:
        model = StaffProfile
        fields = ["id", "first_name", "last_name", "email", "designation", "staff_role_display", "is_active", "joining_date","address", "blood_group",]

# Subject create serializer
class SubjectSerializer(serializers.ModelSerializer):
    # Accepts an array of department assignments with distinct semesters/years
    assignments = DepartmentSubjectMappingSerializer(source="department_mappings", many=True)
    subject_type_display = serializers.CharField(source="get_subject_type_display", read_only=True)
    class Meta:
        model = Subject
        fields = ["id","college","name","code","short_name", "subject_type","subject_type_display","credits","assignments","is_active","created_at",]
        read_only_fields = ["id", "created_at"]

    def validate_code(self, value):
        value = value.strip().upper()
        queryset = Subject.objects.filter(code__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError("This subject code has already been created. Please enter a different subject code.")
        return value

    def create(self, validated_data):
        mappings_data = validated_data.pop("department_mappings", [])
        subject = Subject.objects.create(**validated_data)
        
        # Create individual mappings for each department assignment
        for mapping in mappings_data:
            DepartmentSubjectMapping.objects.create(subject=subject, **mapping)
            
        return subject
    
# Subject List serializers
class SubjectListSerializer(serializers.ModelSerializer):
    department_names = serializers.SlugRelatedField(source="departments",many=True,read_only=True,slug_field="short_name")
    subject_type_display = serializers.CharField(source="get_subject_type_display", read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "name", "code","short_name", "department_names","subject_type", "subject_type_display", "credits", "is_active"]
        
class SubjectUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ["name", "code","short_name", "subject_type", "credits", "is_active"]

    def validate_code(self, value):
        qs = Subject.objects.filter(college=self.instance.college, code=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another subject in this college already uses this code.")
        return value
    
class MappingTeacherUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentSubjectMapping
        fields = ["teacher", "year", "semester"]

    def validate(self, attrs):
        instance = self.instance
        year = attrs.get("year", instance.year)
        semester = attrs.get("semester", instance.semester)

        qs = DepartmentSubjectMapping.objects.filter(subject=instance.subject,department=instance.department,year=year,semester=semester,).exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A mapping already exists for this department/year/semester combination.")
        return attrs


class MappingTeacherUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepartmentSubjectMapping
        fields = ["teacher"]
        
# Create student profile serializers
class StudentCreateSerializer(serializers.ModelSerializer):
    # ---- User fields ----
    email = serializers.EmailField(write_only=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    mobile_number = serializers.CharField(write_only=True, required=False, allow_null=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)

    class Meta:
        model = StudentProfile
        fields = ["id","email","first_name","last_name","mobile_number","address","blood_group","emergency_contact_number", "admission_number","roll_number","department","academic_year","year","semester","section","date_of_birth","is_active","created_at", "qualifying_marks_percentage", "is_merit_scholarship","is_first_generation_graduate", "status", "graduation_date", "is_hostellar"]
        read_only_fields = ["id", "created_at","is_merit_scholarship","is_active"]

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_admission_number(self, value):
        if StudentProfile.objects.filter(admission_number=value).exists():
            raise serializers.ValidationError("A user with this admission number already exists.")
        return value
    
    
    def validate_mobile_number(self, value):
        if value and User.objects.filter(mobile_number=value).exists():
            raise serializers.ValidationError("A user with this mobile number already exists.")
        return value
    
    def validate_qualifying_marks_percentage(self, value):
        if value is not None and not (0 <= value <= 100):
            raise serializers.ValidationError("Must be between 0 and 100.")
        return value

    def validate_academic_year(self, value):
        if value and not value.strip():
            return value
        if value:
            parts = value.split("-")
            if len(parts) != 2 or not all(p.isdigit() and len(p) == 4 for p in parts):
                raise serializers.ValidationError("Use the format YYYY-YYYY, e.g. 2024-2025.")
        return value

    def validate(self, attrs):
        # Semester must belong to the selected year (2 semesters per year), when both are given
        year = attrs.get("year")
        semester = attrs.get("semester")
        if year and semester:
            valid_semesters = {2 * year - 1, 2 * year}
            if semester not in valid_semesters:
                raise serializers.ValidationError({"semester": f"Year {year} only allows semesters {sorted(valid_semesters)}."})
        status = attrs.get("status")
        graduation_date = attrs.get("graduation_date")
        if status == "graduated" and not graduation_date:
            raise serializers.ValidationError({"graduation_date": "Required when status is 'graduated'."})
        return attrs

    def create(self, validated_data):
        email = validated_data.pop("email")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        mobile_number = validated_data.pop("mobile_number", None)
        college = validated_data.pop("college")
        admission_number = validated_data.get("admission_number", "")
        chars = string.ascii_letters + string.digits + "!@#$%^&*"
        generated_password = get_random_string(length=10, allowed_chars=chars)
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generated_password,
                    first_name=first_name,
                    last_name=last_name,
                    mobile_number=mobile_number,
                    user_type="college_user",
                )
                college_user = CollegeUser.objects.create(
                    user=user,
                    college=college,
                    role="student",
                    employee_or_student_id=admission_number,
                )
                student_profile = StudentProfile.objects.create(
                    college_user=college_user,
                    college=college,
                    **validated_data,
                )
                if student_profile.qualifying_marks_percentage is not None:
                    student_profile.evaluate_merit_scholarship()
                    
                student_profile.generated_password = generated_password
                student_profile.admission_number = admission_number
        except IntegrityError as e:
            error_msg = str(e).lower()
            if "mobile" in error_msg or "phone" in error_msg if "phone" in error_msg else False:
                raise serializers.ValidationError({"mobile_number": ["A user with this mobile number already exists."]})
            elif "admission_number" in error_msg:
                raise serializers.ValidationError({"admission_number": ["A student with this admission number already exists in this college."]})
            elif "email" in error_msg:
                raise serializers.ValidationError({"email": ["A user with this email already exists."]})
            raise serializers.ValidationError({"non_field_errors": ["A database conflict occurred while saving the student record."]})

        return student_profile

# Students list serializers
class StudentListSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    status = serializers.CharField(source="college_user.status", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    year_display = serializers.CharField(source="get_year_display", read_only=True, default=None)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True, default=None)

    class Meta:
        model = StudentProfile
        fields = ["id","name","email","admission_number","address", "blood_group", "emergency_contact_number","roll_number","department_name","academic_year","year","year_display","semester","semester_display","section","status","is_active",]

    def get_name(self, obj):
        user = obj.college_user.user
        full_name = f"{user.first_name} {user.last_name}".strip()
        return full_name or user.email
    
    
# ---------------------------------------------------------------------------
# Student profile edit — active status, DOB, section, roll no., admission no.
# ---------------------------------------------------------------------------
class StudentProfileUpdateSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="college_user.user.first_name", max_length=150)
    last_name = serializers.CharField(source="college_user.user.last_name", max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(source="college_user.user.email")
    mobile_number = serializers.CharField(source="college_user.user.mobile_number", max_length=16,required=False, allow_blank=True, allow_null=True,)
    send_password = serializers.BooleanField(write_only=True, required=False, default=False)

    class Meta:
        model = StudentProfile
        fields = ["is_active", "date_of_birth", "section", "roll_number", "admission_number","address", "blood_group", "emergency_contact_number","department", "year", "semester","first_name", "last_name", "email", "mobile_number", "send_password",]

    def validate_admission_number(self, value):
        qs = StudentProfile.objects.filter(college=self.instance.college, admission_number=value).exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Another student in this college already uses this admission number.")
        return value

    def validate_email(self, value):
        qs = User.objects.filter(email__iexact=value).exclude(pk=self.instance.college_user.user_id)
        if qs.exists():
            raise serializers.ValidationError("This email is already in use.")
        return value

    def validate_mobile_number(self, value):
        if value:
            qs = User.objects.filter(mobile_number=value).exclude(pk=self.instance.college_user.user_id)
            if qs.exists():
                raise serializers.ValidationError("This mobile number is already in use.")
        return value

    def update(self, instance, validated_data):
        validated_data.pop("send_password", None)
        college_user_data = validated_data.pop("college_user", {})
        user_data = college_user_data.pop("user", {}) if college_user_data else {}

        if user_data:
            user = instance.college_user.user
            if "email" in user_data:
                user_data["username"] = user_data["email"]  # keep login in sync
            for attr, val in user_data.items():
                setattr(user, attr, val)
            user.save(update_fields=list(user_data.keys()))

        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        return instance


class StudentDetailSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="college_user.user.first_name", read_only=True)
    last_name = serializers.CharField(source="college_user.user.last_name", read_only=True)
    email = serializers.CharField(source="college_user.user.email", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)

    class Meta:
        model = StudentProfile
        fields = [
            "id", "first_name", "last_name", "email", "admission_number", "roll_number",
            "academic_year", "department_name", "year_display", "semester_display",
            "section", "date_of_birth", "is_active","address", "blood_group", "emergency_contact_number"
        ]
    
# ---------------------------------------------------------------------------
# Create Classroom Serializers
# ---------------------------------------------------------------------------
    
def _check_same_college(obj, college, label):
    if obj.college_id != college.id:
        raise serializers.ValidationError(f"{label} does not belong to your college.")
 
 
def _check_year_open(academic_year):
    """Past academic years are read-only history."""
    if not academic_year.is_current:
        raise serializers.ValidationError(
            f"Academic year {academic_year.name} is closed. Its data is read-only."
        )
        
def _check_classroom_open(classroom):
    if not classroom_is_open(classroom):
        raise serializers.ValidationError(
            f"{classroom.name} is closed (past term). Its timetable and attendance are read-only.")
        
ACADEMIC_YEAR_NAME_RE = re.compile(r"^(\d{4})-(\d{4})$")

class AcademicYearInlineSerializer(serializers.Serializer):
    """Used to create an academic year together with the first classroom."""
    name = serializers.CharField(max_length=9, help_text="e.g. 2025-2026")
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    is_current = serializers.BooleanField(required=False, default=False)
 
    def validate_name(self, value):
        value = value.strip()
        m = ACADEMIC_YEAR_NAME_RE.match(value)
        if not m or int(m.group(2)) != int(m.group(1)) + 1:
            raise serializers.ValidationError("Use the format YYYY-YYYY, e.g. 2025-2026.")
        if AcademicYear.objects.filter(college=self.context["college"], name=value).exists():
            raise serializers.ValidationError(f"Academic year {value} already exists. Select it from the list.")
        return value
 
    def validate(self, attrs):
        if attrs["start_date"] >= attrs["end_date"]:
            raise serializers.ValidationError({"end_date": "End date must be after start date."})
        overlap = AcademicYear.objects.filter(
            college=self.context["college"],
            start_date__lt=attrs["end_date"], end_date__gt=attrs["start_date"],
        ).first()
        if overlap:
            raise serializers.ValidationError({"start_date": f"These dates overlap with academic year {overlap.name}."})
        return attrs
    
    
def create_academic_year(college, data):
    """The first academic year of a college is always made current; later ones only if requested."""
    has_current = AcademicYear.objects.filter(college=college, is_current=True).exists()
    make_current = bool(data.get("is_current")) or not has_current
    if make_current:
        AcademicYear.objects.filter(college=college, is_current=True).update(is_current=False)
    return AcademicYear.objects.create(
        college=college, name=data["name"], start_date=data["start_date"],
        end_date=data["end_date"], is_current=make_current,
    )

class ClassroomCreateSerializer(serializers.ModelSerializer):
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all())
    academic_year = serializers.PrimaryKeyRelatedField(queryset=AcademicYear.objects.all(), required=False)
    new_academic_year = AcademicYearInlineSerializer(write_only=True, required=False)
    student_ids = serializers.ListField(child=serializers.UUIDField(), write_only=True, required=False, default=list)
    class Meta:
        model = Classroom
        fields = ["id", "academic_year","new_academic_year","department", "section", "room_number", "year", "semester","student_ids"]
        read_only_fields = ["id"]
    
    def validate_department(self, value):
        _check_same_college(value, self.context["college"], "Department")
        return value
 
    def validate_academic_year(self, value):
        _check_same_college(value, self.context["college"], "Academic year")
        return value
 
    def validate(self, attrs):
        college = self.context["college"]
        new_ay = attrs.get("new_academic_year")
        academic_year = attrs.get("academic_year") or AcademicYear.objects.filter(college=college, is_current=True).first()
        student_ids = attrs.get("student_ids") or []
        if new_ay and academic_year:
            raise serializers.ValidationError("Choose an existing academic year or create a new one, not both.")
        if not new_ay:
            academic_year = academic_year or AcademicYear.objects.filter(college=college, is_current=True).first()
            if academic_year is None:
                raise serializers.ValidationError({"academic_year": "Select an academic year, or enter the details of a new one."})
            attrs["academic_year"] = academic_year
            
        department = attrs.get("department")
        year = attrs.get("year")
        semester = attrs.get("semester")
        section = attrs.get("section", "")
        if year and semester:
            valid_semesters = {2 * year - 1, 2 * year}
            if semester not in valid_semesters:
                raise serializers.ValidationError({"semester": f"Year {year} only allows semesters {sorted(valid_semesters)}."})
 
        if academic_year and department and year and semester is not None:
            if Classroom.objects.filter(college=college, academic_year=academic_year, department=department,year=year, semester=semester, section=section,).exists():
                raise serializers.ValidationError({"section": f"This classroom already exists for {academic_year.name}."})
        
        if student_ids:
            if new_ay:
                has_current = AcademicYear.objects.filter(college=college, is_current=True).exists()
                will_be_current = bool(new_ay.get("is_current")) or not has_current
            else:
                will_be_current = academic_year.is_current
            if not will_be_current:
                raise serializers.ValidationError({"student_ids": "Students can only be enrolled into the current academic year."})

            students = list(StudentProfile.objects.filter(
                id__in=student_ids, college=college, is_active=True, status="active",
                department=department, year=year, semester=semester))
            if len(students) != len(set(student_ids)):
                raise serializers.ValidationError({"student_ids": "Some selected students don't match this department, year and semester."})
            attrs["students"] = students
            
        return attrs
 
    @transaction.atomic
    def create(self, validated_data):
        validated_data.pop("student_ids", None)
        students = validated_data.pop("students", [])
        new_ay = validated_data.pop("new_academic_year", None)
        if new_ay:
            validated_data["academic_year"] = create_academic_year(validated_data["college"], new_ay)

        dept = validated_data["department"]
        validated_data["name"] = f"{dept.short_name or dept.code} - Section {validated_data.get('section', '')}"[:50]

        classroom = super().create(validated_data)
        for s in students:
            enroll_student(s, classroom)
        return classroom
 
# ---------------------------------------------------------------------------
# Classroom List Serializers
# ---------------------------------------------------------------------------
 
class ClassroomListSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", read_only=True)
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)
 
    class Meta:
        model = Classroom
        fields = ["id", "name", "section", "room_number","academic_year","academic_year_name","department", "department_name", "year", "year_display","semester", "semester_display",]

 
class ClassroomSerializer(ClassroomListSerializer):
    pass

# ---------------------------------------------------------------------------
# TimeTable Slot Create
# ---------------------------------------------------------------------------  


class TimetableSlotCreateSerializer(serializers.ModelSerializer):
    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.select_related("academic_year"))
    subject_mapping = serializers.PrimaryKeyRelatedField(queryset=DepartmentSubjectMapping.objects.all())
    teacher = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
 
    class Meta:
        model = TimetableSlot
        fields = [
            "id", "classroom", "subject_mapping", "teacher",
            "day_of_week", "period_number", "start_time", "end_time",
        ]
        read_only_fields = ["id"]
 
    def validate(self, attrs):
        classroom = attrs["classroom"]
        _check_same_college(classroom, self.context["college"], "Classroom")
        _check_classroom_open(classroom)
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        sm = attrs["subject_mapping"]
        if (sm.department_id, sm.year, sm.semester) != (classroom.department_id, classroom.year, classroom.semester):
            raise serializers.ValidationError(
                {"subject_mapping": "This subject is not mapped to the classroom's department / year / semester."}
            )
        return attrs
 
# ---------------------------------------------------------------------------
# TimeTable Slot List
# --------------------------------------------------------------------------- 

class _TeacherNameMixin:
    def get_teacher_name(self, obj):
        if not obj.teacher:
            return "Unassigned"
        full_name = f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        return full_name or obj.teacher.email

class TimetableSlotListSerializer(_TeacherNameMixin,serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject_mapping.subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject_mapping.subject.code", read_only=True)
    teacher_name = serializers.SerializerMethodField()
    day_display = serializers.CharField(source="get_day_of_week_display", read_only=True)
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)
 
    class Meta:
        model = TimetableSlot
        fields = ["id", "classroom","academic_year", "academic_year_name", "day_of_week", "day_display", "period_number","start_time", "end_time", "subject_name", "subject_code", "teacher_name",]
 
    def get_teacher_name(self, obj):
        if not obj.teacher:
            return "Unassigned"
        full_name = f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        return full_name or obj.teacher.email
    

    

# ---------------------------------------------------------------------------
# Bulk grid save — one Subject x Period matrix for a classroom's single day.
# clearing a cell back to "Not Scheduled" removes its slot too.
# ---------------------------------------------------------------------------
class TimetableGridCellSerializer(serializers.Serializer):
    subject_mapping = serializers.PrimaryKeyRelatedField(queryset=DepartmentSubjectMapping.objects.all())
    day_of_week = serializers.ChoiceField(choices=TimetableSlot.DAYS_OF_WEEK)
    period_number = serializers.IntegerField(min_value=1, max_value=12)
    teacher = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()

    def validate(self, attrs):
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "End time must be after start time."})
        return attrs
 
 
class TimetableGridSaveSerializer(serializers.Serializer):
    classroom = serializers.PrimaryKeyRelatedField(queryset=Classroom.objects.all())
    cells = TimetableGridCellSerializer(many=True)
    
    def validate_classroom(self, classroom):
        _check_same_college(classroom, self.context["college"], "Classroom")
        _check_classroom_open(classroom)
        return classroom

    def validate_cells(self, value):
        seen = set()
        for c in value:
            key = (c["day_of_week"], c["period_number"])
            if key in seen:
                raise serializers.ValidationError("Two subjects can't be assigned to the same period on the same day — clear one first.")
            seen.add(key)
        return value

    def validate(self, attrs):
        classroom = attrs["classroom"]
        for cell in attrs["cells"]:
            sm = cell["subject_mapping"]
            if (sm.department_id, sm.year, sm.semester) != (classroom.department_id, classroom.year, classroom.semester):
                raise serializers.ValidationError("A subject in the grid doesn't belong to this classroom's department / year / semester.")
            teacher = cell.get("teacher")
            if not teacher:
                continue
            clash = (TimetableSlot.objects.filter(teacher=teacher, day_of_week=cell["day_of_week"], period_number=cell["period_number"]).exclude(classroom=classroom).select_related("classroom").first())
            if clash:
                raise serializers.ValidationError(f"{teacher.first_name or teacher.email} is already teaching "f"{clash.classroom.name} at Period {cell['period_number']} on this day.")
        return attrs

    def save(self):
        from django.db import transaction
        classroom = self.validated_data["classroom"]
        cells = self.validated_data["cells"]

        with transaction.atomic():
            existing = {
                (s.day_of_week, s.period_number): s
                for s in TimetableSlot.objects.select_for_update().filter(classroom=classroom)
            }
            wanted = {(c["day_of_week"], c["period_number"]) for c in cells}
            removed = [s for key, s in existing.items() if key not in wanted]
            locked = [s for s in removed if s.attendance_sessions.exists()]
            if locked:
                raise serializers.ValidationError(
                    "Cannot remove periods that already have attendance recorded: "
                    + ", ".join(f"{s.get_day_of_week_display()} P{s.period_number}" for s in locked)
                )
            # TimetableSlot.objects.filter(classroom=classroom).delete()
            saved = []
            for cell in cells:
                key = (cell["day_of_week"], cell["period_number"])
                slot = existing.get(key) or TimetableSlot(classroom=classroom, day_of_week=key[0], period_number=key[1])
                slot.subject_mapping = cell["subject_mapping"]
                slot.teacher = cell.get("teacher")
                slot.start_time = cell["start_time"]
                slot.end_time = cell["end_time"]
                slot.save()  # model.save() copies academic_year from classroom
                saved.append(slot)
        return saved 
# ---------------------------------------------------------------------------
# Classroom Serializers
# ---------------------------------------------------------------------------
class ClassroomSerializer(serializers.ModelSerializer):
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)
 
    class Meta:
        model = Classroom
        fields = [
            "id", "name", "section", "room_number",
            "department", "year", "year_display", "semester", "semester_display",
        ]
 
 
class TimetableSlotSerializer(_TeacherNameMixin,serializers.ModelSerializer):
    subject_name = serializers.CharField(source="subject_mapping.subject.name", read_only=True)
    subject_code = serializers.CharField(source="subject_mapping.subject.code", read_only=True)
    day_label = serializers.CharField(source="get_day_of_week_display", read_only=True)
    teacher_name = serializers.SerializerMethodField()
 
    class Meta:
        model = TimetableSlot
        fields = [
            "id", "day_of_week","day_label", "period_number", "start_time", "end_time",
            "subject_name", "subject_code", "teacher_name",
        ]
 
    def get_teacher_name(self, obj):
        if not obj.teacher:
            return "Unassigned"
        full_name = f"{obj.teacher.first_name} {obj.teacher.last_name}".strip()
        return full_name or obj.teacher.email
 
 
# ---------------------------------------------------------------------------
# Bulk save for the matrix view — one date, many periods, many students
# ---------------------------------------------------------------------------
class AttendanceRecordInputSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all())
    status = serializers.ChoiceField(choices=StudentAttendance.STATUS_CHOICES)
    remarks = serializers.CharField(required=False, allow_blank=True, max_length=150)


class AttendancePeriodEntrySerializer(serializers.Serializer):
    timetable_slot = serializers.PrimaryKeyRelatedField(queryset=TimetableSlot.objects.select_related("classroom__academic_year"))
    records = AttendanceRecordInputSerializer(many=True)

    def validate_records(self, value):
        if not value:
            raise serializers.ValidationError("At least one attendance record is required.")
        student_ids = [r["student"].id for r in value]
        if len(student_ids) != len(set(student_ids)):
            raise serializers.ValidationError("Duplicate student entries in the same submission.")
        return value


class SaveAttendanceMatrixSerializer(serializers.Serializer):
    date = serializers.DateField()
    entries = AttendancePeriodEntrySerializer(many=True)
    def validate_date(self, value):
        if value > date.today():
            raise serializers.ValidationError("Attendance can't be recorded for a future date.")
        return value

    def validate_entries(self, value):
        if not value:
            raise serializers.ValidationError("No periods submitted.")
        return value

    def validate(self, attrs):
        college = self.context["college"]
        date_ = attrs["date"]
        roster_cache = {}  # classroom_id -> set(student ids)
        for entry in attrs["entries"]:
            slot = entry["timetable_slot"]
            classroom = slot.classroom
            ay = classroom.academic_year
            _check_same_college(classroom, college, "Classroom")
            _check_classroom_open(classroom)
            if not (ay.start_date <= date_ <= ay.end_date):
                raise serializers.ValidationError(f"{date_} is outside academic year {ay.name}.")
            if slot.day_of_week != date_.weekday() + 1:
                raise serializers.ValidationError(f"Period {slot.period_number} is a {slot.get_day_of_week_display()} period, not on {date_}.")
            if classroom.id not in roster_cache:
                roster_cache[classroom.id] = set(StudentEnrollment.objects.filter(classroom=classroom, is_active=True).values_list("student_id", flat=True))
            for record in entry["records"]:
                if record["student"].id not in roster_cache[classroom.id]:
                    raise serializers.ValidationError(f"Student {record['student'].id} is not enrolled in {classroom.name}.")
        return attrs

    def save(self, taken_by, editable_slot_ids):
        date_ = self.validated_data["date"]
        entries = self.validated_data["entries"]
        for entry in entries:
            slot = entry["timetable_slot"]
            if slot.id not in editable_slot_ids:
                raise PermissionDenied(f"You don't have permission to edit Period {slot.period_number}.")
        sessions_touched = []

        with transaction.atomic():
            for entry in entries:
                slot = entry["timetable_slot"]
                session, _ = PeriodAttendanceSession.objects.get_or_create(timetable_slot=slot, date=date_, defaults={"taken_by": taken_by},)  # model.save() copies academic_year from the slot
                session.is_completed = True
                session.taken_by = taken_by
                session.save(update_fields=["is_completed", "taken_by"])
                existing = {r.student_id: r for r in StudentAttendance.objects.filter(session=session)}
                to_create, to_update = [], []
                for rec in entry["records"]:
                    obj = existing.get(rec["student"].id)
                    if obj:
                        obj.status = rec["status"]
                        obj.remarks = rec.get("remarks", "")
                        to_update.append(obj)
                    else:
                        to_create.append(StudentAttendance(session=session, student=rec["student"],status=rec["status"], remarks=rec.get("remarks", ""),))
                StudentAttendance.objects.bulk_create(to_create)
                StudentAttendance.objects.bulk_update(to_update, ["status", "remarks"])
                sessions_touched.append(session)
        return sessions_touched
 
    
    
    
# ================================================================
# NOTE :- STUDENTS DATA SERALIZERS
# ================================================================


class SubjectMiniSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    code = serializers.CharField()
    name = serializers.CharField()
    short_name = serializers.CharField()
    subject_type = serializers.CharField()
    credits = serializers.IntegerField()
    teacher_name = serializers.SerializerMethodField()

    def get_teacher_name(self, obj):
        teacher = getattr(obj, "teacher", None)
        if teacher and teacher.college_user and teacher.college_user.user:
            u = teacher.college_user.user
            return f"{u.first_name} {u.last_name}".strip() or u.email
        return None



class AttendanceSummarySerializer(serializers.Serializer):
    total_sessions = serializers.IntegerField()
    present_count = serializers.IntegerField()
    absent_count = serializers.IntegerField()
    late_count = serializers.IntegerField()
    on_duty_count = serializers.IntegerField()
    percentage = serializers.FloatField()


class SubjectAttendanceSerializer(serializers.Serializer):
    subject_code = serializers.CharField()
    subject_name = serializers.CharField()
    total = serializers.IntegerField()
    present = serializers.IntegerField()
    percentage = serializers.FloatField()


class StudentDashboardSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    mobile_number = serializers.CharField(source="college_user.user.mobile_number", read_only=True)
    college_name = serializers.CharField(source="college.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True)
    department_short = serializers.CharField(source="department.short_name", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)

    attendance_summary = serializers.SerializerMethodField()
    attendance_by_subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    timetable = serializers.SerializerMethodField()
    todays_classes = serializers.SerializerMethodField()

    class Meta:
        model = StudentProfile
        fields = [
            "id", "full_name", "email", "mobile_number",
            "admission_number", "roll_number", "academic_year",
            "college_name", "department_name", "department_short",
            "year", "year_display", "semester", "semester_display", "section",
            "date_of_birth", "blood_group", "emergency_contact_number", "address",
            "is_active",
            "attendance_summary", "attendance_by_subject", "subjects",
            "timetable", "todays_classes",
        ]

    def get_full_name(self, obj):
        u = obj.college_user.user
        return f"{u.first_name} {u.last_name}".strip() or u.email

    def _classroom(self, obj):
        return Classroom.objects.filter(college=obj.college, department=obj.department,year=obj.year, semester=obj.semester, section=obj.section,).first()

    def get_attendance_summary(self, obj):
        qs = StudentAttendance.objects.filter(student=obj)
        agg = qs.aggregate(total=Count("id"),present=Count("id", filter=Q(status="P")),absent=Count("id", filter=Q(status="A")),late=Count("id", filter=Q(status="L")),on_duty=Count("id", filter=Q(status="OD")),)
        total = agg["total"] or 0
        present_equiv = agg["present"] + agg["late"] + agg["on_duty"]
        percentage = round((present_equiv / total) * 100, 1) if total else 0.0
        return AttendanceSummarySerializer({"total_sessions": total,"present_count": agg["present"],"absent_count": agg["absent"],"late_count": agg["late"],"on_duty_count": agg["on_duty"],"percentage": percentage,}).data

    def get_attendance_by_subject(self, obj):
        qs = (StudentAttendance.objects.filter(student=obj).values("session__timetable_slot__subject_mapping__subject__code","session__timetable_slot__subject_mapping__subject__name",).annotate(total=Count("id"),present=Count("id", filter=Q(status__in=["P", "L", "OD"])),))
        result = []
        for row in qs:
            total = row["total"] or 0
            present = row["present"] or 0
            result.append({"subject_code": row["session__timetable_slot__subject_mapping__subject__code"] or "—","subject_name": row["session__timetable_slot__subject_mapping__subject__name"] or "Unknown","total": total,"present": present,"percentage": round((present / total) * 100, 1) if total else 0.0,})
        return SubjectAttendanceSerializer(result, many=True).data

    def get_subjects(self, obj):
        mappings = (
            DepartmentSubjectMapping.objects.filter(
                department=obj.department, year=obj.year, semester=obj.semester,
            )
            .select_related("subject", "teacher__college_user__user")
        )
        subjects = []
        for m in mappings:
            subjects.append({"id": m.subject.id,"code": m.subject.code,"name": m.subject.name,"short_name": m.subject.short_name,"subject_type": m.subject.subject_type,"credits": m.subject.credits,"teacher": m.teacher,})
        # Reuse SubjectMiniSerializer-style shaping via manual dict (avoids needing model instances)
        out = []
        for s in subjects:
            teacher = s.pop("teacher")
            teacher_name = None
            if teacher and teacher.college_user and teacher.college_user.user:
                u = teacher.college_user.user
                teacher_name = f"{u.first_name} {u.last_name}".strip() or u.email
            s["teacher_name"] = teacher_name
            out.append(s)
        return out

    def get_timetable(self, obj):
        classroom = self._classroom(obj)
        if not classroom:
            return []
        slots = (TimetableSlot.objects.filter(classroom=classroom).select_related("subject_mapping__subject", "teacher").order_by("day_of_week", "period_number"))
        return TimetableSlotSerializer(slots, many=True).data

    def get_todays_classes(self, obj):
        classroom = self._classroom(obj)
        if not classroom:
            return []
        today_weekday = timezone.localdate().isoweekday()  # 1=Mon..7=Sun
        if today_weekday > 6:  # Sunday not in DAYS_OF_WEEK
            return []
        slots = (
            TimetableSlot.objects.filter(classroom=classroom, day_of_week=today_weekday).select_related("subject_mapping__subject", "teacher").order_by("period_number"))
        return TimetableSlotSerializer(slots, many=True).data
    
 
class CalendarDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    day_number = serializers.IntegerField()
    in_month = serializers.BooleanField()
    is_today = serializers.BooleanField()
    status = serializers.ChoiceField(
        choices=["present", "absent", "late", "on_duty", "holiday", "future"]
    )
    status_label = serializers.CharField(allow_null=True)
 
 
class AttendanceCalendarSerializer(serializers.Serializer):
    month_label = serializers.CharField()          # e.g. "September 2026"
    month = serializers.CharField()                 # e.g. "2026-09"
    prev_month = serializers.CharField()
    next_month = serializers.CharField()
    weeks = serializers.ListField(
        child=serializers.ListField(child=CalendarDaySerializer())
    )
   
   
class StudentProfileSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    mobile_number = serializers.CharField(source="college_user.user.mobile_number", read_only=True)
    college_name = serializers.CharField(source="college.name", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    department_short = serializers.CharField(source="department.short_name", read_only=True, default=None)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)
    blood_group_display = serializers.CharField(source="get_blood_group_display", read_only=True)

    class Meta:
        model = StudentProfile
        fields = ["id","full_name","email","mobile_number","admission_number","roll_number","academic_year","college_name","department_name","department_short","year_display","semester_display","section","date_of_birth","address","blood_group_display","emergency_contact_number","is_active",]

    def get_full_name(self, obj):
        user = obj.college_user.user
        return user.get_full_name() or user.email


class RequestPasswordOTPSerializer(serializers.Serializer):
    """No input needed — OTP always goes to the logged-in user's own email."""
    pass


class VerifyPasswordOTPSerializer(serializers.Serializer):
    otp = serializers.CharField(min_length=6, max_length=6)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return attrs
   
class PromoteStudentsSerializer(serializers.Serializer):
    students = serializers.PrimaryKeyRelatedField(queryset=StudentProfile.objects.all(), many=True)
    year = serializers.IntegerField(min_value=1, max_value=4, required=False)
    semester = serializers.IntegerField(min_value=1, max_value=8, required=False)
    section = serializers.CharField(required=False, allow_blank=True, max_length=50)
    academic_year = serializers.CharField(required=False, allow_blank=True, max_length=9)
 
    def validate_students(self, value):
        if not value:
            raise serializers.ValidationError("Select at least one student.")
        college = self.context.get("college")
        if college:
            outside = [s.id for s in value if s.college_id != college.id]
            if outside:
                raise serializers.ValidationError("One or more selected students don't belong to your college.")
        return value
 
    def validate_academic_year(self, value):
        if value:
            parts = value.split("-")
            if len(parts) != 2 or not all(p.isdigit() and len(p) == 4 for p in parts):
                raise serializers.ValidationError("Use the format YYYY-YYYY, e.g. 2026-2027.")
        return value
 
    def validate(self, attrs):
        update_keys = {"year", "semester", "section", "academic_year"} & set(attrs.keys())
        # Drop blank strings so "leave unchanged" is unambiguous
        for key in ("section", "academic_year"):
            if attrs.get(key) == "":
                attrs.pop(key, None)
                update_keys.discard(key)
        if not update_keys:
            raise serializers.ValidationError("Provide at least one field to update.")
        year = attrs.get("year")
        semester = attrs.get("semester")
        # If only the year is given, default to the first semester of that year
        if year and semester is None:
            attrs["semester"] = 2 * year - 1
        elif year and semester:
            valid_semesters = {2 * year - 1, 2 * year}
            if semester not in valid_semesters:
                raise serializers.ValidationError({"semester": f"Year {year} only allows semesters {sorted(valid_semesters)}."})
        return attrs
 
    def save(self):
        college = self.context["college"]
        d = self.validated_data

        with transaction.atomic():
            target_ay = resolve_target_academic_year(college, d.get("academic_year"))
            if target_ay is None:
                raise serializers.ValidationError({"academic_year": "No current academic year is set. Enter the target academic year."})

            promoted, skipped, rooms_created = 0, [], 0
            room_cache = {}
            left_rooms = set()   

            for s in d["students"]:
                year = d.get("year", s.year)
                semester = d.get("semester", s.semester)
                section = d.get("section", s.section) or ""
                tag = s.admission_number

                if not (s.department_id and year and semester):
                    skipped.append(f"{tag}: department, year or semester is missing")
                    continue
                if semester not in (2 * year - 1, 2 * year):
                    skipped.append(f"{tag}: semester {semester} doesn't belong to year {year}")
                    continue

                key = (s.department_id, year, semester, section)
                if key not in room_cache:
                    room_cache[key], created = get_or_create_classroom(college, target_ay, s.department, year, semester, section)
                    rooms_created += int(created)

                try:
                    with transaction.atomic():           # one failure doesn't roll back the others
                        old = list(StudentEnrollment.objects.filter(student=s, status="active")
                                   .values_list("classroom_id", flat=True))
                        enroll_student(s, room_cache[key])
                        left_rooms.update(old)
                    promoted += 1
                except EnrollmentConflict as e:
                    skipped.append(f"{tag}: {e}")
                
            today = timezone.localdate()
            for c in Classroom.objects.filter(id__in=left_rooms, is_active=True):
                if not c.enrollments.filter(status="active").exists():
                    c.is_active, c.closed_on = False, today
                    c.save(update_fields=["is_active", "closed_on"])

        return {"promoted": promoted, "classrooms_created": rooms_created, "skipped": skipped}
    
 
# ---------------------------------------------------------------------------
# INPUT — one dynamic row on the "Create Fee Structure" page
# (name / code / amount [/ semester]). This is NOT a ModelSerializer for
# FeeCategory because the category may or may not exist yet — it's
# get_or_create'd inside FeeStructureCreateSerializer.create().
# ---------------------------------------------------------------------------
class FeeStructureItemInputSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=FeeCategory.objects.filter(is_active=True), required=False, allow_null=True)
    name = serializers.CharField(required=False, allow_blank=True)
    code = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    semester = serializers.IntegerField(required=False, allow_null=True)
    is_optional = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        category = attrs.get("category")
        name = (attrs.get("name") or "").strip()
        code = (attrs.get("code") or "").strip().upper()

        if not category and not (name and code):
            raise serializers.ValidationError("Select an existing fee type or provide both a name and a code.")

        attrs["name"] = name
        # For an existing category, the category's own code is the source of truth
        attrs["code"] = category.code if category else code
        return attrs
 
# ---------------------------------------------------------------------------
# CREATE — the whole page submits ONE payload: FeeStructure fields +
# a list of items. This serializer creates all three tables atomically.
# ---------------------------------------------------------------------------
class FeeStructureCreateSerializer(serializers.ModelSerializer):
    items = FeeStructureItemInputSerializer(many=True, write_only=True)
    class Meta:
        model = FeeStructure
        fields = ["id","college","department","year","academic_year","billing_cycle","items",]
        read_only_fields = ["id"]
        extra_kwargs = {"department": {"required": False, "allow_null": True},}
 
    # -- field-level validation --------------------------------------------
    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one fee item.")
        return value
 
    # -- object-level validation ---------------------------------------------
    def validate(self, attrs):
        college = attrs["college"]
        department = attrs.get("department")
        year = attrs["year"]
        academic_year = attrs["academic_year"]          # AcademicYear instance
        billing_cycle = attrs.get("billing_cycle", "semester")
        items = attrs["items"]

        # The college must be the requesting user's own college
        request = self.context.get("request")
        if request is not None:
            is_member = CollegeUser.objects.filter(user=request.user, college=college, status="active").exists()
            if not is_member:
                raise serializers.ValidationError({"college": "You do not belong to this college."})

        # Everything referenced must belong to the same college
        if academic_year.college_id != college.id:
            raise serializers.ValidationError({"academic_year": "Academic year does not belong to this college."})
        if department and department.college_id != college.id:
            raise serializers.ValidationError({"department": "Department does not belong to this college."})

        # One structure per college + department + year + academic_year
        if FeeStructure.objects.filter(college=college, department=department, year=year, academic_year=academic_year).exists():
            raise serializers.ValidationError("A fee structure already exists for this department, year and academic year.")

        # Semester rules
        if billing_cycle == "semester":
            valid_semesters = {year * 2 - 1, year * 2}      # year 1 -> sems 1,2 ... year 4 -> 7,8
            for item in items:
                sem = item.get("semester")
                if sem is not None and sem not in valid_semesters:
                    raise serializers.ValidationError(
                        {"items": f"Semester {sem} does not belong to year {year}."}
                    )
        else:
            # Year-wise billing ignores semester on every line item.
            for item in items:
                item["semester"] = None

        # Category checks + duplicate detection (by resolved code + semester)
        seen = set()
        for item in items:
            category = item.get("category")
            if category and category.college_id != college.id:
                raise serializers.ValidationError(
                    {"items": f"Fee type '{category.name}' does not belong to this college."}
                )
            key = (item["code"], item.get("semester"))
            if key in seen:
                raise serializers.ValidationError(
                    {"items": f"Duplicate fee item '{item['code']}' for the same semester."}
                )
            seen.add(key)

        return attrs

    # -- create: FeeStructure + resolve/create FeeCategory + FeeStructureItem --
    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        college = validated_data["college"]
        fee_structure = FeeStructure.objects.create(**validated_data)

        item_objs = []
        for item in items_data:
            category = item.get("category")
            if category is None:
                category, _ = FeeCategory.objects.get_or_create(college=college,code=item["code"],defaults={"name": item["name"], "is_optional": item.get("is_optional", False)},)
            item_objs.append(FeeStructureItem(fee_structure=fee_structure,category=category,amount=item["amount"],semester=item.get("semester"),))
        FeeStructureItem.objects.bulk_create(item_objs)
        return fee_structure
 
# ---------------------------------------------------------------------------
# OUTPUT — for listing / confirming what was created
# ---------------------------------------------------------------------------
class FeeStructureItemOutputSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    class Meta:
        model = FeeStructureItem
        fields = ["id", "category_name", "category_code", "amount", "semester", "is_active"]
 
 
class FeeStructureDetailSerializer(serializers.ModelSerializer):
    items = FeeStructureItemOutputSerializer(many=True, read_only=True)
    department_name = serializers.SerializerMethodField()
    billing_cycle_display = serializers.CharField(source="get_billing_cycle_display", read_only=True)
 
    class Meta:
        model = FeeStructure
        fields = ["id","college","department","department_name","year","academic_year","billing_cycle","billing_cycle_display","is_active","items",]
 
    def get_department_name(self, obj):
        return obj.department.name if obj.department else "All Departments"
 
 
 
# ---------------------------------------------------------------------------
# OUTPUT — a student who could be assigned this fee structure
# ---------------------------------------------------------------------------
class EligibleStudentSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    department_name = serializers.CharField(source="department.short_name", read_only=True, default=None)
    already_invoiced = serializers.SerializerMethodField()
    class Meta:
        model = StudentProfile
        fields = [
            "id", "admission_number", "roll_number", "name", "department_name",
            "year", "semester", "section", "is_hostellar", "already_invoiced",
        ]
 
    def get_name(self, obj):
        user = obj.college_user.user
        return user.get_full_name() or user.username
 
    def get_already_invoiced(self, obj):
        invoiced_ids = self.context.get("invoiced_student_ids", set())
        return obj.id in invoiced_ids
 
 
# ---------------------------------------------------------------------------
# OUTPUT — a generated invoice, with its snapshotted line items
# ---------------------------------------------------------------------------
class StudentFeeInvoiceItemOutputSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)
    concession_reason = serializers.CharField(source="concession.get_reason_display", read_only=True, default=None)
 
    class Meta:
        model = StudentFeeInvoiceItem
        fields = ["id", "category_name", "category_code", "gross_amount","concession", "concession_reason", "concession_amount", "amount",]
 
 
class StudentFeeInvoiceOutputSerializer(serializers.ModelSerializer):
    items = StudentFeeInvoiceItemOutputSerializer(many=True, read_only=True)
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    balance_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    class Meta:
        model = StudentFeeInvoice
        fields = ["id", "invoice_number", "student", "student_name", "admission_number","fee_structure", "academic_year", "semester", "total_amount","discount_amount", "balance_due", "amount_paid", "due_date","status", "status_display", "generated_at", "items",]
 
    def get_student_name(self, obj):
        user = obj.student.college_user.user
        return user.get_full_name() or user.username
 
 

# ---------------------------------------------------------------------------
# INPUT — assign a fee structure to a set of students
# ---------------------------------------------------------------------------
class AssignFeeStructureSerializer(serializers.Serializer):
    fee_structure = serializers.PrimaryKeyRelatedField(queryset=FeeStructure.objects.filter(is_active=True))
    student_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    semester = serializers.IntegerField(required=False, allow_null=True, default=None)
    due_date = serializers.DateField()
 
    def validate_student_ids(self, value):
        seen, deduped = set(), []
        for sid in value:
            if sid not in seen:
                seen.add(sid)
                deduped.append(sid)
        return deduped
 
    def validate(self, attrs):
        fee_structure = attrs["fee_structure"]
 
        if fee_structure.billing_cycle == "semester":
            semester = attrs.get("semester")
            if semester is None:
                raise serializers.ValidationError({"semester": "Semester is required for a semester-wise fee structure."})
            if not (1 <= semester <= 8):
                raise serializers.ValidationError({"semester": "Semester must be between 1 and 8."})
        else:
            attrs["semester"] = None  # year-wise billing ignores semester
 
        students = list(StudentProfile.objects.filter(id__in=attrs["student_ids"], college_id=fee_structure.college_id))
        found_ids = {str(s.id) for s in students}
        missing = [str(sid) for sid in attrs["student_ids"] if str(sid) not in found_ids]
        if missing:
            raise serializers.ValidationError({"student_ids": f"These students were not found in this college: {', '.join(missing)}"})
 
        attrs["students"] = students
        return attrs
    
    
    

# ---------------------------------------------------------------------------
# A single payment attempt/record shown in an invoice's payment history
# ---------------------------------------------------------------------------
class FeePaymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)
    payment_type_display = serializers.CharField(source="get_payment_type_display", read_only=True)
 
    class Meta:
        model = FeePayment
        fields = ["id", "receipt_number", "amount","payment_type", "payment_type_display","payment_mode", "payment_mode_display","status", "status_display","gateway_name", "gateway_transaction_id","paid_at", "created_at",]
 
 
# ---------------------------------------------------------------------------
# List page — one row per invoice, no items/payments (keeps it light)
# ---------------------------------------------------------------------------
class StudentFeeInvoiceListSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    balance_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    department_name = serializers.SerializerMethodField()
    year = serializers.IntegerField(source="fee_structure.year", read_only=True)
    can_pay = serializers.SerializerMethodField()
 
    class Meta:
        model = StudentFeeInvoice
        fields = ["id", "invoice_number", "academic_year", "semester", "year","department_name", "total_amount", "discount_amount","amount_paid", "balance_due", "due_date","status", "status_display", "can_pay", "generated_at",]
 
    def get_department_name(self, obj):
        dept = obj.fee_structure
        return dept if dept else "All Departments"
 
    def get_can_pay(self, obj):
        return obj.status in ("pending", "partial", "overdue") and obj.balance_due > 0
 
 
# ---------------------------------------------------------------------------
# Detail page — full breakdown for the "clear invoice" screen
# ---------------------------------------------------------------------------
class StudentFeeInvoiceDetailSerializer(StudentFeeInvoiceListSerializer):
    items = StudentFeeInvoiceItemOutputSerializer(many=True, read_only=True)
    payments = FeePaymentSerializer(many=True, read_only=True)
    class Meta(StudentFeeInvoiceListSerializer.Meta):
        fields = StudentFeeInvoiceListSerializer.Meta.fields + ["items", "payments"]
 
 
# ---------------------------------------------------------------------------
# Response shape after generating/reusing a payment link for "Pay Now"
# ---------------------------------------------------------------------------
class PaymentGatewayLinkSerializer(serializers.ModelSerializer):
    url = serializers.CharField(read_only=True)
    class Meta:
        model = PaymentGatewayLink
        fields = ["id", "url", "amount", "status", "expires_at"]
         
        

class FeeCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeCategory
        fields = ["id", "name", "code", "description", "is_optional", "is_active"]
        read_only_fields = ["id"]
 
 
class FeeStructureSerializer(serializers.ModelSerializer):
    college_name = serializers.CharField(source="college.name", read_only=True)
    department_name = serializers.SerializerMethodField()
    billing_cycle_display = serializers.CharField(source="get_billing_cycle_display", read_only=True)
 
    class Meta:
        model = FeeStructure
        fields = [
            "id", "college", "college_name", "department", "department_name",
            "year", "academic_year", "billing_cycle", "billing_cycle_display", "is_active",
        ]
        read_only_fields = ["id"]
 
    def get_department_name(self, obj):
        return obj.department.short_name if obj.department else "All Departments"
 
 
class FeeStructureItemSerializer(serializers.ModelSerializer):
    """Used for listing/editing/deleting a single existing item."""
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_is_optional = serializers.BooleanField(source="category.is_optional", read_only=True)
 
    class Meta:
        model = FeeStructureItem
        fields = [
            "id", "fee_structure", "category", "category_name", "category_is_optional",
            "amount", "semester", "is_active", "created_at",
        ]
        read_only_fields = ["id", "created_at"]
 
    def validate(self, attrs):
        fee_structure = attrs.get("fee_structure") or getattr(self.instance, "fee_structure", None)
        category = attrs.get("category") or getattr(self.instance, "category", None)
        semester = attrs.get("semester", getattr(self.instance, "semester", None))
        amount = attrs.get("amount", getattr(self.instance, "amount", None))
 
        if amount is not None and amount < 0:
            raise serializers.ValidationError({"amount": "Amount cannot be negative."})
 
        if fee_structure and category and category.college_id != fee_structure.college_id:
            raise serializers.ValidationError({"category": "This fee category belongs to a different college."})
 
        if fee_structure and fee_structure.billing_cycle == "year" and semester:
            raise serializers.ValidationError({"semester": "Year-wise structures should not set a semester on an item."})

        if fee_structure and category:
            qs = FeeStructureItem.objects.filter(fee_structure=fee_structure, category=category, semester=semester)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("An item for this category and semester already exists on this structure.")
        return attrs
 

 
 
class FeeStructureItemBulkCreateSerializer(serializers.Serializer):
    
    fee_structure = serializers.PrimaryKeyRelatedField(queryset=FeeStructure.objects.all())
    items = FeeStructureItemInputSerializer(many=True, min_length=1)
 
    def validate(self, attrs):
        fee_structure = attrs["fee_structure"]
        items = attrs["items"]
        seen = set()
 
        for row in items:
            category = row["category"]
            # Year-wise structures ignore semester entirely, regardless of
            # what the client sent — normalize it here rather than trust the payload.
            semester = row.get("semester") if fee_structure.billing_cycle == "semester" else None
            row["semester"] = semester
 
            if category.college_id != fee_structure.college_id:
                raise serializers.ValidationError(f"Category '{category.name}' belongs to a different college than this fee structure.")
 
            key = (category.id, semester)
            if key in seen:
                raise serializers.ValidationError(f"'{category.name}' is listed more than once for the same semester in this submission.")
            seen.add(key)
 
            if FeeStructureItem.objects.filter(fee_structure=fee_structure, category=category, semester=semester).exists():
                raise serializers.ValidationError(f"'{category.name}' already has an item on this structure for that semester.")
 
        return attrs
 
    def create(self, validated_data):
        fee_structure = validated_data["fee_structure"]
        rows = validated_data["items"]
        objs = [
            FeeStructureItem(
                fee_structure=fee_structure,
                category=row["category"],
                amount=row["amount"],
                semester=row["semester"],
                is_active=row["is_active"],
            )
            for row in rows
        ]
        return FeeStructureItem.objects.bulk_create(objs)
 
 
class FeeStructureItemsSummarySerializer(serializers.Serializer):
    fee_structure = FeeStructureSerializer(read_only=True)
    items = FeeStructureItemSerializer(many=True, read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    active_items = serializers.IntegerField(read_only=True)
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
 
    @staticmethod
    def build(fee_structure, items_queryset):
        items = list(items_queryset)
        active_items = [i for i in items if i.is_active]
        return {
            "fee_structure": fee_structure,
            "items": items,
            "total_items": len(items),
            "active_items": len(active_items),
            "total_amount": sum((i.amount for i in active_items), start=0),
        }
        
 
# ---------------------------------------------------------------------------
# FeeStructure — list page: one row per structure, grouped by department
# in the view. Keep this light — no nested items, just a count + total.
# ---------------------------------------------------------------------------
class FeeStructureListSerializer(serializers.ModelSerializer):
    department_id = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    billing_cycle_display = serializers.CharField(source="get_billing_cycle_display", read_only=True)
    academic_year = serializers.CharField(source="academic_year.name",read_only=True)
    item_count = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
 
    class Meta:
        model = FeeStructure
        fields = [
            "id",
            "department_id",
            "department_name",
            "year",
            "year_display",
            "academic_year",
            "billing_cycle",
            "billing_cycle_display",
            "item_count",
            "total_amount",
            "is_active",
        ]
 
    def get_department_id(self, obj):
        return str(obj.department_id) if obj.department_id else None
 
    def get_department_name(self, obj):
        return obj.department.name if obj.department_id else "All Departments"
 
    def get_item_count(self, obj):
        # obj.items is prefetched in the view — use the cached list, don't re-query.
        return len([i for i in obj.items.all() if i.is_active])
 
    def get_total_amount(self, obj):
        return sum((i.amount for i in obj.items.all() if i.is_active), start=0)
 
 
# ---------------------------------------------------------------------------
# FeeStructure — detail page: full structure + all its items.
# ---------------------------------------------------------------------------
class FeeStructureDetailSerializer(serializers.ModelSerializer):
    department_id = serializers.SerializerMethodField()
    department_name = serializers.SerializerMethodField()
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    billing_cycle_display = serializers.CharField(source="get_billing_cycle_display", read_only=True)
    items = FeeStructureItemSerializer(many=True, read_only=True)
    total_amount = serializers.SerializerMethodField()
 
    class Meta:
        model = FeeStructure
        fields = [
            "id",
            "department_id",
            "department_name",
            "year",
            "year_display",
            "academic_year",
            "academic_year_name",
            "billing_cycle",
            "billing_cycle_display",
            "items",
            "total_amount",
            "is_active",
            "created_at",
            "updated_at",
        ]
 
    def get_department_id(self, obj):
        return str(obj.department_id) if obj.department_id else None
 
    def get_department_name(self, obj):
        return obj.department.name if obj.department_id else "All Departments"
 
    def get_total_amount(self, obj):
        return sum((i.amount for i in obj.items.all() if i.is_active), start=0)
 
 
# ---------------------------------------------------------------------------
# Write serializers — used by the "Create Fee Structure" page (GET form / POST save)
# ---------------------------------------------------------------------------
class FeeStructureItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructureItem
        fields = ["category", "amount", "semester"]
 
 
class FeeStructureWriteSerializer(serializers.ModelSerializer):
    items = FeeStructureItemWriteSerializer(many=True, required=False)
 
    class Meta:
        model = FeeStructure
        fields = [
            "id",
            "college",
            "department",
            "year",
            "academic_year",
            "billing_cycle",
            "items",
        ]
        read_only_fields = ["id"]
 
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        structure = FeeStructure.objects.create(**validated_data)
        for item_data in items_data:
            FeeStructureItem.objects.create(fee_structure=structure, **item_data)
        return structure
    
    

class StudentPreviewSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    department_name = serializers.CharField(source="department.short_name", default="", read_only=True)

    class Meta:
        model = StudentProfile
        fields = ["id", "admission_number", "name", "department_name", "year", "semester", "is_hostellar"]

    def get_name(self, obj):
        u = obj.college_user.user
        return f"{u.first_name} {u.last_name}".strip()


class BulkInvoiceTargetSerializer(serializers.Serializer):
    """Shared target-resolution logic used by both preview and generate."""
    target_type = serializers.ChoiceField(choices=BulkFeeInvoiceBatch.TARGET_TYPE_CHOICES)
    department_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    year = serializers.ChoiceField(choices=YEAR_CHOICES, required=False, allow_null=True)
    hostellers_only = serializers.BooleanField(required=False, default=False)
    student_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)

    def validate(self, attrs):
        if attrs["target_type"] == "department" and not attrs.get("department_ids"):
            raise serializers.ValidationError({"department_ids": "Select at least one department."})
        if attrs["target_type"] == "manual" and not attrs.get("student_ids"):
            raise serializers.ValidationError({"student_ids": "Select at least one student."})
        return attrs

    def get_queryset(self, college):
        data = self.validated_data
        qs = StudentProfile.objects.filter(college=college, is_active=True, status="active")

        target = data["target_type"]
        if target == "department":
            qs = qs.filter(department_id__in=data["department_ids"])
        elif target == "hostellers":
            qs = qs.filter(is_hostellar=True)
        elif target == "manual":
            qs = qs.filter(id__in=data["student_ids"])
        # target == "all": no extra filter

        if data.get("year"):
            qs = qs.filter(year=data["year"])
        if data.get("hostellers_only") and target != "hostellers":
            qs = qs.filter(is_hostellar=True)

        return qs.select_related("college_user__user", "department")


class BulkInvoiceGenerateSerializer(BulkInvoiceTargetSerializer):
    category = serializers.PrimaryKeyRelatedField(queryset=FeeCategory.objects.all())
    title = serializers.CharField(max_length=150)
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    amount_per_student = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    academic_year = serializers.CharField(max_length=9)
    semester = serializers.ChoiceField(choices=SEMESTER_CHOICES, required=False, allow_null=True)
    due_date = serializers.DateField()

    def validate_category(self, value):
        college = self.context["college"]
        if value.college_id != college.id:
            raise serializers.ValidationError("Invalid fee category for this college.")
        if value.name.strip().lower() != "others":
            raise serializers.ValidationError("Bulk invoices can only be created under the 'Others' category.")
        return value


class BulkFeeInvoiceBatchSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    department_names = serializers.SerializerMethodField()
    generated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = BulkFeeInvoiceBatch
        fields = ["id", "title", "remarks", "category", "category_name", "amount_per_student","academic_year", "semester", "target_type", "department_names", "year_filter","hostellers_only", "due_date", "status", "total_students_targeted","total_invoices_created", "total_amount", "failure_reason","generated_by_name", "created_at",]

    def get_department_names(self, obj):
        return [d.short_name or d.name for d in obj.departments.all()]

    def get_generated_by_name(self, obj):
        u = obj.generated_by
        if not u:
            return None
        full = f"{u.first_name} {u.last_name}".strip()
        return full or u.email


class BulkFeeInvoiceBatchStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    department_name = serializers.CharField(source="student.department.short_name", default="", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", default=None, read_only=True)

    class Meta:
        model = BulkFeeInvoiceBatchStudent
        fields = ["id", "student", "student_name", "admission_number", "department_name","invoice", "invoice_number", "status", "skip_reason",]

    def get_student_name(self, obj):
        u = obj.student.college_user.user
        return f"{u.first_name} {u.last_name}".strip()
    
    
class FeePaymentListSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    department_name = serializers.CharField(source="student.department.short_name", default="", read_only=True)
    year = serializers.IntegerField(source="student.year", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)

    class Meta:
        model = FeePayment
        fields = ["id", "receipt_number", "student", "student_name", "admission_number","department_name", "year", "invoice", "invoice_number","payment_type", "payment_mode", "amount", "status", "paid_at", "created_at",]

    def get_student_name(self, obj):
        u = obj.student.college_user.user
        return f"{u.first_name} {u.last_name}".strip()


class FeePaymentDetailSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    department_name = serializers.CharField(source="student.department.short_name", default="", read_only=True)
    year = serializers.IntegerField(source="student.year", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    invoice_total = serializers.DecimalField(source="invoice.total_amount", max_digits=10, decimal_places=2, read_only=True)
    collected_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FeePayment
        fields = ["id", "receipt_number", "student", "student_name", "admission_number", "department_name", "year","invoice", "invoice_number", "invoice_total","payment_type", "payment_mode", "amount","gateway_name", "gateway_transaction_id", "gateway_order_id","cheque_or_dd_number", "bank_name", "collected_by", "collected_by_name","status", "paid_at", "remarks", "created_at", "updated_at",]

    def get_student_name(self, obj):
        u = obj.student.college_user.user
        return f"{u.first_name} {u.last_name}".strip()

    def get_collected_by_name(self, obj):
        if not obj.collected_by:
            return None
        full = f"{obj.collected_by.first_name} {obj.collected_by.last_name}".strip()
        return full or obj.collected_by.email


OFFLINE_MODES = ("cash", "cheque", "dd", "bank_transfer")

class FeePaymentConvertToOfflineSerializer(serializers.Serializer):
    payment_mode = serializers.ChoiceField(choices=[c for c in FeePayment.PAYMENT_MODE_CHOICES if c[0] in OFFLINE_MODES])
    cheque_or_dd_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    mark_as_paid = serializers.BooleanField(default=True)

    def validate(self, attrs):
        mode = attrs["payment_mode"]
        if mode in ("cheque", "dd") and not attrs.get("cheque_or_dd_number"):
            raise serializers.ValidationError({"cheque_or_dd_number": "Required for cheque/DD payments."})
        if mode in ("cheque", "dd", "bank_transfer") and not attrs.get("bank_name"):
            raise serializers.ValidationError({"bank_name": "Bank name is required for this payment mode."})
        return attrs
    
    
# ---------------------------------------------------------------------------
# ADMIN — invoice history page. Distinct names from StudentFeeInvoiceList/
# DetailSerializer (which are student-facing) to avoid clobbering them.
# Reads department/year off `student`, not `fee_structure`, since bulk
# invoices always have fee_structure=None.
# ---------------------------------------------------------------------------
class AdminInvoicePaymentSerializer(serializers.ModelSerializer):
    """Richer than the student-facing FeePaymentSerializer — includes who
    collected an offline payment and the cheque/bank details, which a
    student doesn't need to see but an admin reviewing history does."""
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)
    payment_type_display = serializers.CharField(source="get_payment_type_display", read_only=True)
    collected_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FeePayment
        fields = [
            "id", "receipt_number", "amount",
            "payment_type", "payment_type_display",
            "payment_mode", "payment_mode_display",
            "status", "status_display",
            "gateway_name", "gateway_transaction_id",
            "cheque_or_dd_number", "bank_name", "collected_by", "collected_by_name",
            "remarks", "paid_at", "created_at",
        ]

    def get_collected_by_name(self, obj):
        if not obj.collected_by:
            return None
        full = f"{obj.collected_by.first_name} {obj.collected_by.last_name}".strip()
        return full or obj.collected_by.email


class AdminInvoiceListSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    department_name = serializers.CharField(source="student.department.short_name", default="", read_only=True)
    year = serializers.IntegerField(source="student.year", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    category_names = serializers.SerializerMethodField()
    amount_paid = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    balance_due = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = StudentFeeInvoice
        fields = [
            "id", "invoice_number", "student", "student_name", "admission_number",
            "department_name", "year", "academic_year", "semester",
            "category_names", "total_amount", "discount_amount", "amount_paid", "balance_due",
            "due_date", "status", "status_display", "generated_at",
        ]

    def get_student_name(self, obj):
        u = obj.student.college_user.user
        return f"{u.first_name} {u.last_name}".strip()

    def get_category_names(self, obj):
        return [item.category.name for item in obj.items.all()]


class AdminInvoiceDetailSerializer(AdminInvoiceListSerializer):
    items = StudentFeeInvoiceItemOutputSerializer(many=True, read_only=True)  # reuse — already has everything needed
    payments = AdminInvoicePaymentSerializer(many=True, read_only=True)
    discount_reason = serializers.CharField(read_only=True)

    class Meta(AdminInvoiceListSerializer.Meta):
        fields = AdminInvoiceListSerializer.Meta.fields + ["discount_reason", "items", "payments"]


OFFLINE_MODES = ("cash", "cheque", "dd", "bank_transfer")

class InvoiceOfflinePaymentSerializer(serializers.Serializer):
    """Manually record a payment collected in person against an invoice —
    cash, cheque, DD, or bank transfer."""
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    payment_mode = serializers.ChoiceField(choices=[c for c in FeePayment.PAYMENT_MODE_CHOICES if c[0] in OFFLINE_MODES])
    cheque_or_dd_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    mark_as_paid = serializers.BooleanField(default=True)

    def validate(self, attrs):
        mode = attrs["payment_mode"]
        if mode in ("cheque", "dd") and not attrs.get("cheque_or_dd_number"):
            raise serializers.ValidationError({"cheque_or_dd_number": "Required for cheque/DD payments."})
        if mode in ("cheque", "dd", "bank_transfer") and not attrs.get("bank_name"):
            raise serializers.ValidationError({"bank_name": "Bank name is required for this payment mode."})
        return attrs

    def validate_amount(self, value):
        invoice = self.context["invoice"]
        if value > invoice.balance_due:
            raise serializers.ValidationError(f"Amount exceeds the outstanding balance of ₹{invoice.balance_due}.")
        return value


class InvoiceStatusOverrideSerializer(serializers.Serializer):
    """For statuses that aren't payment-driven — waiving or cancelling an
    invoice outright, rather than recording a payment against it."""
    status = serializers.ChoiceField(choices=[c for c in StudentFeeInvoice.STATUS_CHOICES if c[0] in ("waived", "cancelled")])
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    
    
    
class OfflineCollectionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_number = serializers.CharField(source="student.admission_number", read_only=True)
    department_name = serializers.CharField(source="student.department.short_name", default="", read_only=True)
    year = serializers.IntegerField(source="student.year", read_only=True)
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    payment_mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    collected_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FeePayment
        fields = [
            "id", "receipt_number", "student", "student_name", "admission_number",
            "department_name", "year", "invoice", "invoice_number",
            "payment_mode", "payment_mode_display", "amount",
            "cheque_or_dd_number", "bank_name",
            "status", "status_display", "collected_by", "collected_by_name",
            "remarks", "paid_at", "created_at",
        ]

    def get_student_name(self, obj):
        u = obj.student.college_user.user
        return f"{u.first_name} {u.last_name}".strip()

    def get_collected_by_name(self, obj):
        if not obj.collected_by:
            return None
        full = f"{obj.collected_by.first_name} {obj.collected_by.last_name}".strip()
        return full or obj.collected_by.email


class MarkOfflinePaymentClearedSerializer(serializers.Serializer):
    """For a cheque/DD recorded as pending — confirm it actually cleared."""
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    
    

# ---------------------------------------------------------------- serializers
_MISSING = object()


class ProfileSettingsSerializer(serializers.ModelSerializer):
    department_id = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.none(), required=False, allow_null=True
    )

    class Meta:
        model = CollegeUser
        fields = ["date_of_birth", "blood_group", "emergency_contact_number",
                  "address", "work_experience", "department_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        college = self.context.get("college")
        if college:
            self.fields["department_id"].queryset = Department.objects.filter(college=college)

    def validate_emergency_contact_number(self, value):
        if value:
            digits = value.replace("+", "").replace(" ", "").replace("-", "")
            if not digits.isdigit() or not (7 <= len(digits) <= 15):
                raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate_work_experience(self, value):
        value = (value or "").strip()
        if not value:
            return ""
        m = re.fullmatch(r"(\d{1,2})(\.\d)?\s*(years?|yrs?)?", value, re.I)
        if not m:
            raise serializers.ValidationError("Enter years of experience as a number, e.g. 5 or 2.5.")
        number = m.group(1) + (m.group(2) or "")
        if float(number) > 60:
            raise serializers.ValidationError("Years of experience looks too high.")
        return number

    @transaction.atomic
    def update(self, instance, validated_data):
        dept = validated_data.pop("department_id", _MISSING)
        instance = super().update(instance, validated_data)

        if dept is not _MISSING:
            sp = getattr(instance, "staff_profile", None)
            if sp:
                sp.department = dept
                sp.save(update_fields=["department", "updated_at"])
            instance.department = dept.name if dept else "No Access"
            instance.save(update_fields=["department", "updated_at"])
        return instance
 

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Shared calculation (used by serializers AND the view's summary totals)
# Relies on `payments` (success-only) being prefetched on the invoice.
# ---------------------------------------------------------------------------
def invoice_amounts(inv):
    net = inv.total_amount - inv.discount_amount
    paid = sum((p.amount for p in inv.payments.all()), ZERO)
    balance = ZERO if inv.status == "waived" else max(net - paid, ZERO)
    return {"net": net, "paid": paid, "balance": balance}


# ---------------------------------------------------------------------------
# READ: fee list
# ---------------------------------------------------------------------------
class DepartmentMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ("id", "name", "short_name")


class FeeStudentRowSerializer(serializers.ModelSerializer):
    """One row in the fee list. payment_status / total_due / total_paid are
    attributes set on each instance by _compute_payment_status()."""
    first_name = serializers.CharField(source="college_user.user.first_name", read_only=True)
    last_name = serializers.CharField(source="college_user.user.last_name", read_only=True)
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    semester_display = serializers.CharField(source="get_semester_display", read_only=True)
    payment_status = serializers.CharField(read_only=True)
    total_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = StudentProfile
        fields = (
            "id", "first_name", "last_name", "email", "admission_number", "roll_number",
            "academic_year", "year", "year_display", "semester", "semester_display",
            "section", "payment_status", "total_due", "total_paid",
        )


class YearGroupSerializer(serializers.Serializer):
    academic_year = serializers.CharField()
    students = FeeStudentRowSerializer(many=True)


class DepartmentGroupSerializer(serializers.Serializer):
    department = DepartmentMiniSerializer()
    student_count = serializers.IntegerField()
    year_groups = YearGroupSerializer(many=True)


class StatusCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class PaymentSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    paid = StatusCountSerializer()
    partial = StatusCountSerializer()
    unpaid = StatusCountSerializer()


class FeeListQuerySerializer(serializers.Serializer):
    """Validates the query string. Other filters are still read by _apply_filters()."""
    payment_status = serializers.ChoiceField(choices=["paid", "partial", "unpaid"], required=False, allow_blank=True)
    department = serializers.UUIDField(required=False, allow_null=True)


class FeeListResponseSerializer(serializers.Serializer):
    access_level = serializers.CharField()
    can_open_detail = serializers.BooleanField()
    summary = PaymentSummarySerializer()
    filters = serializers.DictField()
    groups = DepartmentGroupSerializer(many=True)


# ---------------------------------------------------------------------------
# READ: student fee detail
# ---------------------------------------------------------------------------
class StudentFeeHeaderSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source="college_user.user.first_name", read_only=True)
    last_name = serializers.CharField(source="college_user.user.last_name", read_only=True)
    email = serializers.EmailField(source="college_user.user.email", read_only=True)
    department = DepartmentMiniSerializer(read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    fee_deduction_percentage = serializers.SerializerMethodField()

    class Meta:
        model = StudentProfile
        fields = (
            "id", "first_name", "last_name", "email", "admission_number", "roll_number",
            "department", "academic_year", "year", "year_display", "semester",
            "section", "is_hostellar", "is_merit_scholarship",
            "is_first_generation_graduate", "fee_deduction_percentage",
        )

    def get_fee_deduction_percentage(self, obj):
        return obj.get_fee_deduction_percentage()


class FeeStructureItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    is_optional = serializers.BooleanField(source="category.is_optional", read_only=True)

    class Meta:
        model = FeeStructureItem
        fields = ("id", "category_name", "is_optional", "semester", "amount")


class FeeStructureSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source="department.name", default=None, read_only=True)
    year_display = serializers.CharField(source="get_year_display", read_only=True)
    billing_cycle_display = serializers.CharField(source="get_billing_cycle_display", read_only=True)
    items = serializers.SerializerMethodField()

    class Meta:
        model = FeeStructure
        fields = ("id", "academic_year", "year", "year_display", "department_name",
                  "billing_cycle", "billing_cycle_display", "items")

    def get_items(self, obj):
        active = [i for i in obj.items.all() if i.is_active]   # uses prefetch
        return FeeStructureItemSerializer(active, many=True).data


class FeeConcessionSerializer(serializers.ModelSerializer):
    reason_display = serializers.CharField(source="get_reason_display", read_only=True)
    category_name = serializers.CharField(source="category.name", default=None, read_only=True)

    class Meta:
        model = FeeConcession
        fields = ("id", "reason", "reason_display", "reason_detail", "category_name",
                  "concession_type", "value", "is_recurring", "valid_from", "valid_until")


class FeePaymentSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    mode_display = serializers.CharField(source="get_payment_mode_display", read_only=True)
    is_editable = serializers.SerializerMethodField()

    class Meta:
        model = FeePayment
        fields = ("id", "receipt_number", "amount", "payment_type", "payment_mode", "mode_display",
                  "gateway_name", "status", "status_display", "paid_at", "created_at",
                  "remarks", "is_editable")

    def get_is_editable(self, obj):
        return not obj.gateway_transaction_id and not obj.is_settled_to_college


class InvoiceItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = StudentFeeInvoiceItem
        fields = ("id", "category_name", "gross_amount", "concession_amount", "amount")


class StudentFeeInvoiceSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)
    payments = FeePaymentSerializer(source="all_payments", many=True, read_only=True)
    net_amount = serializers.SerializerMethodField()
    amount_paid = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = StudentFeeInvoice
        fields = ("id", "invoice_number", "academic_year", "semester", "due_date",
                  "status", "status_display", "total_amount", "discount_amount",
                  "discount_reason", "net_amount", "amount_paid", "balance_due",
                  "items", "payments")

    def get_net_amount(self, obj):
        return invoice_amounts(obj)["net"]

    def get_amount_paid(self, obj):
        return invoice_amounts(obj)["paid"]

    def get_balance_due(self, obj):
        return invoice_amounts(obj)["balance"]


class FeeSummarySerializer(serializers.Serializer):
    total_billed = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_paid = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_balance = serializers.DecimalField(max_digits=14, decimal_places=2)
    overall_status = serializers.CharField()


class StudentFeeDetailSerializer(serializers.Serializer):
    """Instance is a dict: {student, summary, structures, concessions, invoices}"""
    student = StudentFeeHeaderSerializer()
    summary = FeeSummarySerializer()
    structures = FeeStructureSerializer(many=True)
    concessions = FeeConcessionSerializer(many=True)
    invoices = StudentFeeInvoiceSerializer(many=True)


# ---------------------------------------------------------------------------
# WRITE: edit invoice
# ---------------------------------------------------------------------------
class InvoiceUpdateSerializer(serializers.Serializer):
    discount_amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False)
    discount_reason = serializers.CharField(max_length=255, required=False, allow_blank=True)
    due_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(choices=["auto", "waived", "cancelled"], required=False)

    def validate_discount_amount(self, value):
        if value > self.instance.total_amount:
            raise serializers.ValidationError("Discount cannot exceed the invoice total.")
        return value

    @transaction.atomic
    def update(self, invoice, validated):
        for field in ("discount_amount", "discount_reason", "due_date"):
            if field in validated:
                setattr(invoice, field, validated[field])
        invoice.save()

        status = validated.get("status")
        if status in ("waived", "cancelled"):
            invoice.status = status
            invoice.save(update_fields=["status", "updated_at"])
        elif status == "auto" or invoice.status not in ("waived", "cancelled"):
            invoice.status = "pending"
            invoice.refresh_status()      # recompute from payments
        return invoice


# ---------------------------------------------------------------------------
# WRITE: edit payment (offline, unsettled payments only)
# ---------------------------------------------------------------------------
class PaymentUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[c[0] for c in FeePayment.STATUS_CHOICES], required=False)
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, attrs):
        p = self.instance
        if p.gateway_transaction_id:
            raise serializers.ValidationError("Online gateway payments cannot be edited.")
        if p.is_settled_to_college:
            raise serializers.ValidationError("This payment is already settled to the college.")
        return attrs

    @transaction.atomic
    def update(self, payment, validated):
        from django.utils import timezone
        if "remarks" in validated:
            payment.remarks = validated["remarks"]
        if "status" in validated:
            payment.status = validated["status"]
            if payment.status == "success" and not payment.paid_at:
                payment.paid_at = timezone.now()
        payment.save()
        payment.invoice.refresh_status()
        return payment