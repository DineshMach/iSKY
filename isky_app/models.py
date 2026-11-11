from decimal import Decimal
import uuid,pyotp

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
FIRST_GENERATION_GRADUATE_DEFAULT_PERCENTAGE = 15


class User(AbstractUser):

    USER_TYPE_CHOICES = [("platform_admin", "Platform Admin"),("college_user", "College User"),]
    STATUS_CHOICES = [("active", "Active"),("inactive", "Inactive"),("blocked", "Blocked"),("suspended", "Suspended"),("remove", "Remove")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    mobile_number = models.CharField(max_length=16, unique=True, null=True, blank=True)
    user_type = models.CharField(max_length=30, choices=USER_TYPE_CHOICES, default="college_user")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    password_updated = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    mobile_verified = models.BooleanField(default=False)
    is_2fa_enabled = models.BooleanField(default=False)
    totp_secret = models.CharField(max_length=32, blank=True, null=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_device = models.ForeignKey("TrustedDevice",on_delete=models.SET_NULL,null=True,blank=True,related_name="+")
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def generate_totp_secret(self):
        """Generates a base32 secret for TOTP setup."""
        if not self.totp_secret:
            self.totp_secret = pyotp.random_base32()
            self.save(update_fields=['totp_secret'])
        return self.totp_secret

    def get_totp_uri(self):
        """Generates the provisioning URI for QR codes."""
        secret = self.totp_secret or self.generate_totp_secret()
        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=self.email,
            issuer_name="iSKY App"  # Change to your application name
        )

    def verify_totp(self, code):
        """Verifies a 6-digit TOTP token."""
        if not self.totp_secret:
            return False
        totp = pyotp.TOTP(self.totp_secret)
        # valid_window=1 allows for a 30-second clock drift buffer
        return totp.verify(code, valid_window=1)

    def __str__(self):
        return self.email


class College(models.Model):

    STATUS_CHOICES = [("active", "Active"),("inactive", "Inactive"),("suspended", "Suspended"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=30, unique=True)
    email = models.EmailField()
    mobile_number = models.CharField(max_length=16)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default="India")
    pincode = models.CharField(max_length=10, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

BLOOD_GROUP_CHOICES = [("A+", "A+"),("A-", "A-"),("B+", "B+"),("B-", "B-"),("O+", "O+"),("O-", "O-"),("AB+", "AB+"),("AB-", "AB-"),]
class CollegeUser(models.Model):

    ROLE_CHOICES = [("master_admin", "Master Admin"),("office_admin", "Office Admin"), ("finance_admin", "Finance Admin"),("staff_admin", "Staff Admin"),("student", "Student"),]
    STATUS_CHOICES = [("active", "Active"),("inactive", "Inactive"),("blocked", "Blocked"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="college_memberships")
    college = models.ForeignKey(College,on_delete=models.CASCADE,related_name="users")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    department = models.CharField(max_length=100, default="No Access")
    employee_or_student_id = models.CharField(max_length=100, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=16,null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    work_experience = models.CharField(max_length=150, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "college"],
                name="unique_user_college"
            )
        ]
        indexes = [
            models.Index(fields=["college", "role"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.college} - {self.role}"


class Department(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College,on_delete=models.CASCADE,related_name="departments")
    degree = models.CharField(max_length=200, blank=True,default="B.E")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50)
    short_name = models.CharField(max_length=20,default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["college", "code"],
                name="unique_department_code_per_college"
            )
        ]

    def __str__(self):
        return f"{self.name} - {self.college.name}"


#Subject Model linked to Department and Year
class Subject(models.Model):
    SUBJECT_TYPE_CHOICES = [('theory', 'Theory'),('practical', 'Practical / Lab'),('elective', 'Elective'),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey("College", on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50)
    short_name = models.CharField(max_length=50,default='')
    subject_type = models.CharField(max_length=20, choices=SUBJECT_TYPE_CHOICES, default='theory')
    credits = models.PositiveSmallIntegerField(default=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["college", "code"], name="unique_subject_code_per_college")
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"

def get_ordinal(n):
        if 10 <= n % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
        return f"{n}{suffix}"
    
YEAR_CHOICES = [(1, '1st Year'), (2, '2nd Year'), (3, '3rd Year'), (4, '4th Year')]
SEMESTER_CHOICES = [(i, f"{get_ordinal(i)} Semester") for i in range(1, 9)]

    
class StaffProfile(models.Model):

    STAFF_ROLE_CHOICES = [("hod", "HOD"),("class_advisor", "Class Advisor"),("staff", "Staff"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college_user = models.OneToOneField(CollegeUser,on_delete=models.CASCADE,related_name="staff_profile")
    department = models.ForeignKey(Department,on_delete=models.SET_NULL,null=True,blank=True,related_name="staff_members")
    staff_role = models.CharField(max_length=30,choices=STAFF_ROLE_CHOICES)
    advisor_year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES, null=True, blank=True,help_text="Which year this staff member is class advisor for. Only meaningful when staff_role='class_advisor'.",)
    designation = models.CharField(max_length=150, blank=True)
    joining_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        constraints = [
            # Only one active class advisor per department per year
            models.UniqueConstraint(
                fields=["department", "advisor_year"],
                condition=models.Q(staff_role="class_advisor", is_active=True),
                name="unique_active_class_advisor_per_dept_year",
            )
        ]

    def __str__(self):
        return f"{self.college_user.user} - {self.staff_role}"
    
    
class DepartmentSubjectMapping(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="department_mappings")
    department = models.ForeignKey("Department", on_delete=models.CASCADE, related_name="subject_mappings")
    year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES)
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES)
    # Primary teacher assigned to teach this subject in this department/semester
    teacher = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="subject_mappings")

    class Meta:
        constraints = [
            # Prevents assigning the exact same subject to the same department multiple times
            models.UniqueConstraint(
                fields=["subject", "department"], 
                name="unique_subject_per_department"
            )
        ]

    def __str__(self):
        return f"{self.subject.code} -> {self.department.short_name} (Sem {self.semester})"
    
# ---------------------------------------------------------------------------
# 5c. MERIT SCHOLARSHIP SLAB — the college's own rule table for admission
#     merit scholarships: "95–100% marks -> 100% fee waiver",
#     "90–94.99% -> 90% off", "80–89.99% -> 80% off", etc. Configured once
#     by the college; auto_grant_merit_scholarship() below looks a student's
#     qualifying marks up against this table to decide their concession.
# ---------------------------------------------------------------------------
    
class MeritScholarshipSlab(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="merit_scholarship_slabs")
    admission_academic_year = models.CharField(max_length=9, blank=True)
    label = models.CharField(max_length=100, help_text='e.g. "Full Merit Scholarship", "90% Merit"')
    min_percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text="Inclusive lower bound, e.g. 95.00")
    max_percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text="Inclusive upper bound, e.g. 100.00")
    waiver_percentage = models.DecimalField(max_digits=5, decimal_places=2,help_text="Fee waiver this slab grants: 100 = fully free, 90 = 90% off, etc.",)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-min_percentage"]
        indexes = [
            models.Index(fields=["college", "is_active"]),
        ]

    def matches(self, marks_percentage):
        return self.min_percentage <= marks_percentage <= self.max_percentage

    def __str__(self):
        return f"{self.label}: {self.min_percentage}-{self.max_percentage}% marks -> {self.waiver_percentage}% off"
   
class AcademicYear(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="academic_years")
    name = models.CharField(max_length=9, help_text="e.g. 2025-2026")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(fields=["college", "name"], name="unique_academic_year_per_college"),
            models.UniqueConstraint(fields=["college"],condition=models.Q(is_current=True),name="unique_current_academic_year_per_college",),]

    def clean(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValidationError("Start date must be before end date.")

    def __str__(self):
        return self.name 


class StudentProfile(models.Model):
    STATUS_CHOICES = [("active", "Active"),("graduated", "Graduated"),("dropped_out", "Dropped Out"),("transferred", "Transferred Out"),("suspended", "Suspended"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college_user = models.OneToOneField(CollegeUser,on_delete=models.CASCADE,related_name="student_profile")
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="student_profiles")
    admission_number = models.CharField(max_length=100)
    academic_year = models.CharField( max_length=9,blank=True,db_index=True,help_text="Batch / academic year, format YYYY-YYYY, e.g. 2024-2025",)
    roll_number = models.CharField(max_length=100, blank=True)
    department = models.ForeignKey(Department,on_delete=models.SET_NULL,null=True,blank=True,related_name="students")
    year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES, blank=True,null=True)
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, blank=True,null=True)
    section = models.CharField(max_length=50, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True, null=True)
    emergency_contact_number = models.CharField(max_length=16,null=True, blank=True)
    # ---- Scholarship / fee-deduction eligibility flags ----
    qualifying_marks_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,help_text="12th grade / entrance exam % used to decide merit scholarship eligibility.",)
    is_merit_scholarship = models.BooleanField(default=False,help_text="True once qualifying_marks_percentage has been matched against a ""MeritScholarshipSlab and found eligible. Set via evaluate_merit_scholarship().",)
    is_first_generation_graduate = models.BooleanField(default=False,help_text="First person in their immediate family to pursue a degree.",)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active", db_index=True)
    graduation_date = models.DateField(null=True, blank=True)
    is_hostellar = models.BooleanField(default=False)
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["college_user"],
                name="unique_student_profile"
            ),
            models.UniqueConstraint(
                fields=["college", "admission_number"],
                name="unique_college_admission_number"
            )
        ]
    def save(self, *args, **kwargs):
        # Automatically keep college synced with the college_user relationship
        if self.college_user_id and not self.college_id:
            self.college = self.college_user.college
        super().save(*args, **kwargs)
        
    def evaluate_merit_scholarship(self):
        if self.qualifying_marks_percentage is None:
            self.is_merit_scholarship = False
        else:
            self.is_merit_scholarship = MeritScholarshipSlab.objects.filter(college_id=self.college_id, is_active=True).filter(min_percentage__lte=self.qualifying_marks_percentage,max_percentage__gte=self.qualifying_marks_percentage,).exists()
        self.save(update_fields=["is_merit_scholarship", "updated_at"])
        return self.is_merit_scholarship
 
    def get_fee_deduction_percentage(self):
        merit_pct = 0
        if self.is_merit_scholarship and self.qualifying_marks_percentage is not None:
            slab = MeritScholarshipSlab.objects.filter(college_id=self.college_id, is_active=True,min_percentage__lte=self.qualifying_marks_percentage,max_percentage__gte=self.qualifying_marks_percentage,).order_by("-waiver_percentage").first()
            merit_pct = slab.waiver_percentage if slab else 0
        first_gen_pct = FIRST_GENERATION_GRADUATE_DEFAULT_PERCENTAGE if self.is_first_generation_graduate else 0
 
        return max(merit_pct, first_gen_pct)  # not eligible for either -> 0, i.e. full payment
 
    def calculate_fee(self, gross_amount):
        pct = self.get_fee_deduction_percentage()
        net_amount = gross_amount - (gross_amount * pct / 100)
        return net_amount, pct

    def __str__(self):
        return f"{self.admission_number} - {self.college_user.user}"
    
# 1. CLASSROOM / SECTION MODEL  
class Classroom(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="classrooms")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="classrooms", blank=True, null=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="classrooms")
    name = models.CharField(max_length=50) # e.g. "ECE - Section A"
    room_number = models.CharField(max_length=20, blank=True, null=True)
    section = models.CharField(max_length=20, blank=True)
    year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES,validators=[MinValueValidator(1), MaxValueValidator(4)])
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES,validators=[MinValueValidator(1), MaxValueValidator(8)])
    is_active = models.BooleanField(default=True)       # False = past term, read-only
    closed_on = models.DateField(null=True, blank=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["college", "academic_year", "department", "year", "semester", "section"],name="unique_classroom_per_year_sem_section",)]
        indexes = [models.Index(fields=["college", "academic_year", "department"])]
        
    def __str__(self):
        return f"{self.name} ({self.get_year_display()} - {self.get_semester_display()})"
    
class StudentEnrollment(models.Model):
    STATUS = [("active","Active"),("completed","Completed"),("detained","Detained"),("withdrawn","Withdrawn")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="enrollments", editable=False,null=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="enrollments", editable=False,null=True)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="enrollments")  # copied from classroom
    year = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)       # copied from classroom
    semester = models.PositiveSmallIntegerField(null=True, blank=True, editable=False)
    started_on = models.DateField(default=timezone.localdate)
    ended_on = models.DateField(null=True, blank=True)
    roll_number = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=STATUS, default="active")

    class Meta:
        indexes = [
            models.Index(fields=["academic_year", "semester", "student"]),
            models.Index(fields=["classroom", "academic_year", "year", "semester"]),
        ]

    def save(self, *a, **kw):
        c = self.classroom
        self.academic_year, self.year, self.semester = c.academic_year, c.year, c.semester
        super().save(*a, **kw)
    
# 2. PERIOD TIMETABLE SLOT MODEL (Subject + Staff + Period Assignment)
class TimetableSlot(models.Model):
    DAYS_OF_WEEK = [(1, 'Monday'), (2, 'Tuesday'), (3, 'Wednesday'), (4, 'Thursday'), (5, 'Friday'), (6, 'Saturday')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name="timetable_slots")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="timetable_slots", editable=False,null=True)
    subject_mapping = models.ForeignKey(DepartmentSubjectMapping, on_delete=models.CASCADE, related_name="timetable_slots")
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="assigned_periods")
    day_of_week = models.PositiveSmallIntegerField(choices=DAYS_OF_WEEK)
    period_number = models.PositiveSmallIntegerField()  # e.g., Period 1, Period 2
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["classroom", "day_of_week", "period_number"],
                                    name="unique_classroom_period"),
        ]
        indexes = [models.Index(fields=["academic_year", "teacher"])]

    def save(self, *args, **kwargs):
        self.academic_year = self.classroom.academic_year
        super().save(*args, **kwargs)


# 3. DAILY PERIOD ATTENDANCE SESSION
class PeriodAttendanceSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timetable_slot = models.ForeignKey(TimetableSlot, on_delete=models.PROTECT, related_name="attendance_sessions")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="attendance_sessions", editable=False,null=True)
    classroom = models.ForeignKey(Classroom, on_delete=models.PROTECT, related_name="attendance_sessions", editable=False,null=True)
    subject_mapping = models.ForeignKey(DepartmentSubjectMapping, on_delete=models.PROTECT, editable=False,null=True)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    period_number = models.PositiveSmallIntegerField(null=True)
    semester = models.PositiveSmallIntegerField(null=True)
    date = models.DateField(default=timezone.localdate)
    taken_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["classroom", "date", "period_number"], name="unique_session_per_period_date")]
        indexes = [models.Index(fields=["classroom", "date"]), models.Index(fields=["academic_year", "semester"])]

        


# Assumes YEAR_CHOICES / SEMESTER_CHOICES are shared constants already
# defined elsewhere in your models (same ones used on Subject / Classroom /
# StudentProfile) — import or redefine them if they live in a different module.
# Also assumes College, Department, StudentProfile are defined/imported
# elsewhere in the same app, as in your original file.
# ---------------------------------------------------------------------------
# 1. FEE CATEGORY — the master list of fee types a college can charge.
#    e.g. Tuition Fee, Hostel Fee, Sports Fee, Library Fee, Lab Fee, Exam Fee
# ---------------------------------------------------------------------------
class FeeCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="fee_categories")
    name = models.CharField(max_length=100)                 # e.g. "Tuition Fee"
    code = models.CharField(max_length=30)                  # e.g. "TUITION"
    description = models.CharField(max_length=255, blank=True)
    is_optional = models.BooleanField(default=False,help_text="e.g. Hostel Fee is optional — only charged to students who opted in.",)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["college", "code"], name="unique_fee_category_code_per_college")
        ]

    def __str__(self):
        return f"{self.name} ({self.college.name})"


# ---------------------------------------------------------------------------
# 2. FEE STRUCTURE — a fee plan for a Department + Year, for one academic
#    year, billed either per-semester or per-year (the college's choice).
#    This is the top of the flow:
#       College -> Department -> Year -> Semester -> FeeStructureItem
# ---------------------------------------------------------------------------
class FeeStructure(models.Model):
    BILLING_CYCLE_CHOICES = [("semester", "Semester-wise"), ("year", "Year-wise")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="fee_structures")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True,related_name="fee_structures",help_text="Leave blank to apply this structure to every department.",)
    year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="fee_structures",null=True, blank=True)
    billing_cycle = models.CharField(max_length=10, choices=BILLING_CYCLE_CHOICES, default="semester")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["college", "department", "year", "academic_year"],name="unique_fee_structure_per_dept_year_academic_year",)]
        indexes = [models.Index(fields=["college", "academic_year"], name="feestructure_academic_year")]

    def clean(self):
        if self.academic_year and self.college_id and self.academic_year.college_id != self.college_id:
            raise ValidationError({"academic_year": "Academic year does not belong to this college."})
        if self.department_id and self.college_id and self.department.college_id != self.college_id:
            raise ValidationError({"department": "Department does not belong to this college."})

    def __str__(self):
        dept = self.department.short_name if self.department else "All Depts"
        return f"{dept} · Year {self.year} · {self.academic_year.name} ({self.get_billing_cycle_display()})"






# ---------------------------------------------------------------------------
# 3. FEE STRUCTURE ITEM — the individual fee-type line items that make up a
#    structure (e.g. Tuition: 25000, Hostel: 40000, Sports: 1000), scoped to
#    a semester when billing_cycle == 'semester'.
# ---------------------------------------------------------------------------
class FeeStructureItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fee_structure = models.ForeignKey(FeeStructure, on_delete=models.CASCADE, related_name="items")
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name="structure_items")

    # When billing_cycle == 'semester': this amount applies to ONE semester
    #   (set `semester` to charge a different amount per semester, or leave
    #   it blank to charge the same amount every semester of that year).
    # When billing_cycle == 'year': this amount applies to the WHOLE year
    #   and `semester` is ignored.
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fee_structure", "category", "semester"],name="unique_fee_item_per_structure_category_semester",)]

    def __str__(self):
        return f"{self.category.name} — ₹{self.amount} ({self.fee_structure})"


# ---------------------------------------------------------------------------
# 4. STUDENT FEE INVOICE — one bill generated for a student for one billing
#    period (a semester, or a full year — depending on the structure's
#    billing_cycle). This is the Student node in the
#    Student -> Year -> Semester -> Department -> Payment flow: it snapshots
#    which student, which year/department (via fee_structure) and which
#    semester the bill is for.
# ---------------------------------------------------------------------------
class StudentFeeInvoice(models.Model):
    STATUS_CHOICES = [("pending", "Pending"),("partial", "Partially Paid"),("paid", "Paid"),("overdue", "Overdue"),("waived", "Waived"),("cancelled", "Cancelled"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="fee_invoices")
    fee_structure = models.ForeignKey(FeeStructure, on_delete=models.SET_NULL,null=True,blank=True, related_name="invoices")   # or PROTECT/CASCADE — but must allow null now
    bulk_batch = models.ForeignKey("BulkFeeInvoiceBatch", on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices")
    # Snapshotted at generation time so a later edit to the FeeStructure
    # doesn't silently rewrite history on already-issued invoices.
    academic_year = models.CharField(max_length=9)
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, null=True, blank=True)
    invoice_number = models.CharField(max_length=40, unique=True, editable=False)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_reason = models.CharField(max_length=255, blank=True)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["student", "fee_structure", "semester"],name="unique_invoice_per_student_structure_semester",)]
        indexes = [models.Index(fields=["student", "status"]),models.Index(fields=["academic_year"]),]

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = f"INV-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    @property
    def college(self):
        return self.fee_structure.college

    @property
    def department(self):
        return self.fee_structure.department

    @property
    def year(self):
        return self.fee_structure.year

    @property
    def amount_paid(self):
        return self.payments.filter(status="success").aggregate(
            total=models.Sum("amount")
        )["total"] or 0

    @property
    def balance_due(self):
        return (self.total_amount - self.discount_amount) - self.amount_paid

    def refresh_status(self):
        """Recompute status from recorded payments. Call after saving a payment."""
        if self.status in ("waived", "cancelled"):
            return
        net_payable = self.total_amount - self.discount_amount
        paid = self.amount_paid
        if paid <= 0:
            self.status = "overdue" if timezone.now().date() > self.due_date else "pending"
        elif paid < net_payable:
            self.status = "partial"
        else:
            self.status = "paid"
        self.save(update_fields=["status", "updated_at"])

    def __str__(self):
        return f"{self.invoice_number} — {self.student.admission_number}"
    
    
class BulkFeeInvoiceBatch(models.Model):
    STATUS_CHOICES = [("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed")]
    TARGET_TYPE_CHOICES = [("all", "All Students"),("department", "Selected Departments"),("hostellers", "Hostellers Only"),("manual", "Manually Selected Students"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="bulk_invoice_batches")
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name="bulk_invoice_batches")
    title = models.CharField(max_length=150)  # e.g. "Mess Fee — November 2026"
    remarks = models.CharField(max_length=255, blank=True)
    amount_per_student = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    academic_year = models.CharField(max_length=9)
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, null=True, blank=True,help_text="Optional — attach this charge to a semester for record-keeping (e.g. mess fee billed per semester).")
    target_type = models.CharField(max_length=20, choices=TARGET_TYPE_CHOICES)
    departments = models.ManyToManyField(Department, blank=True, related_name="bulk_invoice_batches")
    year_filter = models.PositiveSmallIntegerField(choices=YEAR_CHOICES, null=True, blank=True)
    hostellers_only = models.BooleanField(default=False)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    total_students_targeted = models.PositiveIntegerField(default=0)
    total_invoices_created = models.PositiveIntegerField(default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    failure_reason = models.CharField(max_length=255, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="bulk_invoice_batches_generated")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["college", "status"])]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"


class BulkFeeInvoiceBatchStudent(models.Model):
    ROW_STATUS_CHOICES = [("created", "Created"), ("skipped", "Skipped"), ("failed", "Failed")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(BulkFeeInvoiceBatch, on_delete=models.CASCADE, related_name="student_rows")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="bulk_invoice_rows")
    invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.SET_NULL, null=True, blank=True,related_name="bulk_batch_row")
    status = models.CharField(max_length=10, choices=ROW_STATUS_CHOICES)
    skip_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["batch", "student"], name="unique_student_per_batch")]

    def __str__(self):
        return f"{self.student.admission_number} — {self.batch.title} ({self.status})"


# ---------------------------------------------------------------------------
# 5a. INVOICE ITEM — snapshot of each fee category & amount making up this
#    invoice, so historical invoices stay correct even if the fee structure
#    (or an individual FeeStructureItem amount) changes afterward.
# ---------------------------------------------------------------------------
class StudentFeeInvoiceItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.CASCADE, related_name="items")
    category = models.ForeignKey(FeeCategory, on_delete=models.PROTECT, related_name="invoice_items")
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    concession = models.ForeignKey("FeeConcession", on_delete=models.SET_NULL, null=True, blank=True,related_name="invoice_items",help_text="Concession applied to this line item, if any, frozen at invoice-generation time.",)
    concession_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["invoice", "category"], name="unique_invoice_item_per_category")]

    def __str__(self):
        return f"{self.category.name}: ₹{self.amount}"
    
    
# ---------------------------------------------------------------------------
# 5b. FEE CONCESSION — the reason a specific student pays less than the
#     standard FeeStructure amount: a merit scholarship for high marks, a
#     sports quota, sibling/staff-ward discount, financial hardship, etc.
#     This is the source of truth (with an approval trail); it's what gets
#     applied when invoices are generated, rather than editing amounts by
#     hand on each invoice.
# ---------------------------------------------------------------------------
class FeeConcession(models.Model):
    REASON_CHOICES = [("merit_scholarship", "Merit Scholarship"),("first_generation_graduate", "First Generation Graduate"),("sports_quota", "Sports Quota"),("sibling_discount", "Sibling Discount"),("staff_ward", "Staff Ward"),("financial_hardship", "Financial Hardship"),("management_discretion", "Management Discretion"),("other", "Other"),]
    CONCESSION_TYPE_CHOICES = [("percentage", "Percentage"), ("fixed", "Fixed Amount")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="fee_concessions")
    # Leave category blank to apply the concession across every category on
    # the invoice (e.g. a blanket 20% merit scholarship on the whole bill).
    category = models.ForeignKey(FeeCategory, on_delete=models.CASCADE, null=True, blank=True, related_name="concessions",help_text="Leave blank to apply to every fee category on the invoice.",)
    reason = models.CharField(max_length=30, choices=REASON_CHOICES)
    reason_detail = models.CharField(max_length=255, blank=True)
    concession_type = models.CharField(max_length=10, choices=CONCESSION_TYPE_CHOICES)
    value = models.DecimalField(max_digits=6, decimal_places=2,help_text="If percentage: e.g. 20 = 20% off. If fixed: a rupee amount off, per applicable billing period.",)
    # Merit scholarships need re-evaluating every year (marks can drop); a
    # sibling discount usually doesn't. is_recurring controls whether it's
    # auto-applied to every future invoice or only within [valid_from, valid_until].
    is_recurring = models.BooleanField(default=False)
    valid_from = models.DateField(default=timezone.now)
    valid_until = models.DateField(null=True, blank=True,help_text="Required for non-recurring concessions (e.g. one semester's merit award). ""Blank + is_recurring=True means 'applies until revoked'.",)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="fee_concessions_approved",)
    approved_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        indexes = [models.Index(fields=["student", "is_active"]),]
 
    def is_applicable_on(self, a_date):
        if not self.is_active:
            return False
        if self.valid_from and a_date < self.valid_from:
            return False
        if self.valid_until and a_date > self.valid_until:
            return False
        return True
 
    def amount_off(self, gross_amount):
        if self.concession_type == "percentage":
            return (gross_amount * self.value) / 100
        return min(self.value, gross_amount)  # a fixed concession can't discount more than the line itself
 
    def __str__(self):
        return f"{self.get_reason_display()} — {self.student.admission_number} ({self.value}{'%' if self.concession_type == 'percentage' else ''})"
 

# ---------------------------------------------------------------------------
# 6. FEE PAYMENT — an actual, recorded payment transaction against an
#    invoice. Supports online (gateway, via PaymentGatewayLink/PaymentHistory
#    below) and offline (cash/cheque/DD/bank transfer) payments. An invoice
#    can receive multiple payments (partial payments over time);
#    amount_paid / balance_due on the invoice sum these up.
#
#    IMPORTANT (settlement model): money for an online payment lands in OUR
#    platform's account first (the gateway settles to us), not directly to
#    the college. This row is the record of "money collected"; whether it
#    has been forwarded to the college yet is tracked separately by
#    SettlementBatchItem, not by this model.
# ---------------------------------------------------------------------------
class FeePayment(models.Model):
    PAYMENT_TYPE_CHOICES = [("online", "Online"), ("offline", "Offline"),("null", "Null")]
    PAYMENT_MODE_CHOICES = [("upi", "UPI"),("card", "Debit/Credit Card"),("netbanking", "Net Banking"),("cash", "Cash"),("cheque", "Cheque"),("dd", "Demand Draft"),("bank_transfer", "Bank Transfer"),]
    STATUS_CHOICES = [("pending", "Pending"),("success", "Success"),("failed", "Failed"),("refunded", "Refunded"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.CASCADE, related_name="payments")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="fee_payments")

    payment_type = models.CharField(max_length=10, choices=PAYMENT_TYPE_CHOICES, blank="null")
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])

    # ---- Online-payment specific ----
    gateway_name = models.CharField(max_length=50, blank=True)          # e.g. "Razorpay", "Stripe"
    gateway_transaction_id = models.CharField(max_length=150, blank=True)
    gateway_order_id = models.CharField(max_length=150, blank=True)

    # ---- Offline-payment specific ----
    cheque_or_dd_number = models.CharField(max_length=50, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="fee_payments_collected",help_text="Office/staff admin who physically received an offline payment.",)
    receipt_number = models.CharField(max_length=40, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    paid_at = models.DateTimeField(null=True, blank=True)
    remarks = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["invoice", "status"]),models.Index(fields=["student", "status"]),]
        # Prevent double-recording the same gateway transaction
        constraints = [models.UniqueConstraint(fields=["gateway_name", "gateway_transaction_id"],name="unique_gateway_transaction",condition=models.Q(gateway_transaction_id__gt=""),)]

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"RCPT-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    @property
    def is_settled_to_college(self):
        item = getattr(self, "settlement_item", None)
        return bool(item and item.is_settled)

    def __str__(self):
        return f"{self.receipt_number} — ₹{self.amount} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# 7. PAYMENT GATEWAY LINK — a payment link OUR platform generates for a
#    student to pay a given invoice online. One invoice can have several
#    links over time (old ones expire/get deactivated, a fresh one is
#    generated on request); only the current one should be "active".
# ---------------------------------------------------------------------------
class PaymentGatewayLink(models.Model):
    LINK_STATUS_CHOICES = [("active", "Active"),("inactive", "Inactive"), ("expired", "Expired"),  ("consumed", "Consumed"), ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.CASCADE, related_name="gateway_links")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="gateway_links")
    token = models.CharField(max_length=64, unique=True, editable=False,help_text="Opaque URL-safe token embedded in the link, e.g. https://pay.ourplatform.com/l/<token>",)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    status = models.CharField(max_length=10, choices=LINK_STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="gateway_links_created",help_text="Staff/admin who triggered link generation, blank if generated by the student themselves.",)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["invoice", "status"]),models.Index(fields=["token"]),]
         # Only one ACTIVE link per invoice at a time. Postgres partial
         # unique index — generating a new link should first flip any
         # existing active link(s) to 'inactive' (see generate helper).
        constraints = [models.UniqueConstraint(fields=["invoice"],condition=models.Q(status="active"),name="unique_active_gateway_link_per_invoice",)]

    @property
    def is_usable(self):
        return self.status == "active" and self.expires_at > timezone.now()

    @property
    def url(self):
        return f"{settings.PAYMENT_LINK_BASE_URL}/{self.token}"

    def __str__(self):
        return f"Link {self.token[:8]}… — {self.invoice.invoice_number} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# 8. PAYMENT HISTORY — one row per payment attempt made against a gateway
#    link, identified by OUR platform's transaction_id. Tracks the raw
#    gateway callback/webhook payload and whether it has been processed
#    into a FeePayment + invoice status update yet (is_callback_updated).
#    A single link can have multiple attempts (e.g. a failed try followed
#    by a successful retry).
# ---------------------------------------------------------------------------
class PaymentHistory(models.Model):
    LINK_STATUS_CHOICES = PaymentGatewayLink.LINK_STATUS_CHOICES
    CALLBACK_STATUS_CHOICES = [("pending", "Pending"),   ("success", "Success"),("failed", "Failed"),("cancelled", "Cancelled"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gateway_link = models.ForeignKey(PaymentGatewayLink, on_delete=models.CASCADE, related_name="payment_attempts")
    invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.CASCADE, related_name="payment_history")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="payment_history")
    transaction_id = models.CharField(max_length=64, unique=True, editable=False,help_text="Our platform's own transaction reference, generated when the attempt starts "
                                      "and passed to the gateway as the client reference.",)
    gateway_name = models.CharField(max_length=50, blank=True)
    gateway_transaction_id = models.CharField(max_length=150, blank=True)
    gateway_order_id = models.CharField(max_length=150, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    link_status = models.CharField(max_length=10, choices=LINK_STATUS_CHOICES, default="active")
    callback_status = models.CharField(max_length=10, choices=CALLBACK_STATUS_CHOICES, default="pending")
    callback_raw_response = models.JSONField(null=True, blank=True,help_text="Raw webhook/callback payload exactly as received from the gateway, for audit/debugging.",)
    callback_received_at = models.DateTimeField(null=True, blank=True)
    is_callback_updated = models.BooleanField(default=False,help_text="True once this callback has been processed into a FeePayment + invoice status update. "
                                              "Lets a webhook handler safely retry/replay without double-crediting a payment.",)
    fee_payment = models.OneToOneField(FeePayment, on_delete=models.SET_NULL, null=True, blank=True,related_name="payment_history_entry",help_text="Set once a successful callback has created the corresponding FeePayment row.",)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Payment histories"
        indexes = [models.Index(fields=["transaction_id"]),models.Index(fields=["invoice", "callback_status"]),models.Index(fields=["is_callback_updated"]),]

    def __str__(self):
        return f"{self.transaction_id} — {self.get_callback_status_display()}"


# ---------------------------------------------------------------------------
# 9. SETTLEMENT BATCH — money for successful online payments lands in OUR
#    platform's account first; we then pay it out to the college in bulk.
#    One batch groups a set of successful FeePayments that get settled to a
#    given college together (e.g. a daily/weekly settlement run).
# ---------------------------------------------------------------------------
class SettlementBatch(models.Model):
    STATUS_CHOICES = [("pending", "Pending"),("processing", "Processing"),("settled", "Settled"),("partially_settled", "Partially Settled"),("failed", "Failed"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    college = models.ForeignKey(College, on_delete=models.PROTECT, related_name="settlement_batches")
    batch_number = models.CharField(max_length=40, unique=True, editable=False)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_transactions = models.PositiveIntegerField(default=0)

    period_from = models.DateTimeField(help_text="Start of the window of successful payments included.")
    period_to = models.DateTimeField(help_text="End of the window of successful payments included.")
    settlement_date = models.DateField(null=True, blank=True, help_text="Date the payout actually reached the college.")
    utr_number = models.CharField(max_length=50, blank=True, help_text="Bank UTR/reference number for the bulk payout to the college.",)
    initiated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="settlement_batches_initiated",)
    remarks = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["college", "status"]),]

    def save(self, *args, **kwargs):
        if not self.batch_number:
            self.batch_number = f"STL-{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)

    def recompute_totals(self):
        agg = self.items.aggregate(total=models.Sum("amount"), count=models.Count("id"))
        self.total_amount = agg["total"] or 0
        self.total_transactions = agg["count"] or 0
        self.save(update_fields=["total_amount", "total_transactions", "updated_at"])

    def refresh_status(self):
        items = self.items.all()
        if not items:
            return
        settled = items.filter(is_settled=True).count()
        total = items.count()
        if settled == total:
            self.status = "settled"
            if not self.settlement_date:
                self.settlement_date = timezone.now().date()
        elif settled == 0:
            self.status = "failed" if self.status == "processing" else self.status
        else:
            self.status = "partially_settled"
        self.save(update_fields=["status", "settlement_date", "updated_at"])

    def __str__(self):
        return f"{self.batch_number} — {self.college.name} ({self.get_status_display()})"


# ---------------------------------------------------------------------------
# 10. SETTLEMENT BATCH ITEM — one successful FeePayment (identified by its
#     gateway/transaction id) inside a batch, and whether it has actually
#     been settled to the college yet. A FeePayment can belong to at most
#     one batch (OneToOne), so the same collected transaction can never be
#     double-counted across settlement runs.
# -----------------------------------------------------------studentenrollment----------------
class SettlementBatchItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(SettlementBatch, on_delete=models.CASCADE, related_name="items")
    fee_payment = models.OneToOneField(FeePayment, on_delete=models.PROTECT, related_name="settlement_item",)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_settled = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["batch", "is_settled"]),]

    def mark_settled(self):
        self.is_settled = True
        self.settled_at = timezone.now()
        self.save(update_fields=["is_settled", "settled_at", "updated_at"])

    def __str__(self):
        return f"{self.fee_payment.receipt_number} in {self.batch.batch_number}"


# 4. INDIVIDUAL STUDENT ATTENDANCE ENTRY
class StudentAttendance(models.Model):
    STATUS_CHOICES = [('P', 'Present'),('A', 'Absent'),('L', 'Late'),('OD', 'On Duty'),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    enrollment = models.ForeignKey(StudentEnrollment, on_delete=models.PROTECT, related_name="attendance", null=True, blank=True)
    session = models.ForeignKey(PeriodAttendanceSession, on_delete=models.CASCADE, related_name="student_records")
    student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="attendances")
    status = models.CharField(max_length=5, choices=STATUS_CHOICES, default='P')
    remarks = models.CharField(max_length=150, blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["student", "session"])]

   




class OTPVerification(models.Model):

    PURPOSE_CHOICES = [("email_verification", "Email Verification"),("mobile_verification", "Mobile Verification"),("login", "Login"),("new_device", "New Device"),("password_reset", "Password Reset"),("2fa", "Two Factor Authentication"),]
    CHANNEL_CHOICES = [("email", "Email"),("sms", "SMS"),("authenticator", "Authenticator"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="otp_verifications")
    purpose = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    otp_hash = models.CharField(max_length=128)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"{self.user} - {self.purpose}"


class TwoFactorAuth(models.Model):

    METHOD_CHOICES = [("authenticator", "Authenticator App"),("email", "Email"),("sms", "SMS"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="two_factor_auth")
    method = models.CharField(max_length=30,choices=METHOD_CHOICES,default="authenticator")
    secret_key = models.CharField(max_length=255, blank=True)
    is_enabled = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    backup_codes_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"2FA - {self.user}"


class TrustedDevice(models.Model):

    DEVICE_TYPE_CHOICES = [("desktop", "Desktop"),("laptop", "Laptop"),("mobile", "Mobile"),("tablet", "Tablet"),("unknown", "Unknown"),]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="trusted_devices")
    device_token_hash = models.CharField(max_length=128, unique=True)
    device_name = models.CharField(max_length=150, blank=True)
    device_type = models.CharField(max_length=20,choices=DEVICE_TYPE_CHOICES,default="unknown")
    browser = models.CharField(max_length=100, blank=True)
    operating_system = models.CharField(max_length=100, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    is_trusted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    first_verified_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["user", "is_trusted"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.device_name}"


class DeviceIPHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(TrustedDevice,on_delete=models.CASCADE,related_name="ip_history")
    ip_address = models.GenericIPAddressField()
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    login_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["device", "ip_address"],
                name="unique_device_ip"
            )
        ]

    def __str__(self):
        return f"{self.device} - {self.ip_address}"


class LoginSecurity(models.Model):

    STATUS_CHOICES = [("active", "Active"),("cooldown", "Cooldown"),("blocked", "Blocked"),("disabled", "Disabled"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="login_security")
    failed_attempts = models.PositiveIntegerField(default=0)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_device = models.ForeignKey(TrustedDevice,on_delete=models.SET_NULL,null=True,blank=True,related_name="+")
    status = models.CharField(max_length=20,choices=STATUS_CHOICES,default="active")
    cooldown_until = models.DateTimeField(null=True, blank=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_in_cooldown(self):
        if not self.cooldown_until:
            return False
        if timezone.now() < self.cooldown_until:
            return True
        self.cooldown_until = None
        if self.status == "cooldown":
            self.status = "active"
        self.save(
            update_fields=[
                "cooldown_until",
                "status",
                "updated_at"
            ]
        )

        return False

    def __str__(self):
        return f"Login Security - {self.user}"


class LoginAttempt(models.Model):

    RESULT_CHOICES = [("success", "Success"),("failed_password", "Failed Password"),("otp_required", "OTP Required"),("otp_failed", "OTP Failed"),("2fa_required", "2FA Required"),("2fa_failed", "2FA Failed"),("new_device", "New Device"),("blocked", "Blocked"),("cooldown", "Cooldown"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="login_attempts")
    ip_address = models.GenericIPAddressField()
    device = models.ForeignKey(TrustedDevice,on_delete=models.SET_NULL,null=True,blank=True,related_name="login_attempts")
    user_agent = models.TextField(blank=True)
    result = models.CharField(max_length=30, choices=RESULT_CHOICES)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-attempted_at"]),
            models.Index(fields=["ip_address", "-attempted_at"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.result}"


class APIThrottleState(models.Model):

    KEY_TYPE_CHOICES = [("user", "User"),("ip", "IP"),("device", "Device"),("anonymous", "Anonymous"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,null=True,blank=True,related_name="api_throttle_states")
    device = models.ForeignKey(TrustedDevice,on_delete=models.CASCADE,null=True,blank=True,related_name="api_throttle_states")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    key_type = models.CharField(max_length=20,choices=KEY_TYPE_CHOICES)
    endpoint = models.CharField(max_length=255)
    request_count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    blocked_until = models.DateTimeField(null=True, blank=True)
    is_blocked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "endpoint"]),
            models.Index(fields=["ip_address", "endpoint"]),
            models.Index(fields=["window_end"]),
        ]

    def __str__(self):
        return f"{self.endpoint} - {self.key_type}"


class APIRequestLog(models.Model):

    STATUS_CHOICES = [("success", "Success"),("failed", "Failed"),("throttled", "Throttled"),("unauthorized", "Unauthorized"),("forbidden", "Forbidden"),("error", "Error"),]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="api_request_logs")
    college = models.ForeignKey(College,on_delete=models.SET_NULL,null=True,blank=True,related_name="api_request_logs")
    device = models.ForeignKey(TrustedDevice,on_delete=models.SET_NULL,null=True,blank=True,related_name="api_request_logs")
    ip_address = models.GenericIPAddressField()
    method = models.CharField(max_length=10)
    endpoint = models.CharField(max_length=500)
    request_id = models.UUIDField(default=uuid.uuid4, db_index=True)
    status_code = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20,choices=STATUS_CHOICES)
    user_agent = models.TextField(blank=True)
    response_time_ms = models.PositiveIntegerField(null=True, blank=True)
    request_size = models.PositiveIntegerField(default=0)
    response_size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["college", "-created_at"]),
            models.Index(fields=["ip_address", "-created_at"]),
            models.Index(fields=["endpoint", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.method} {self.endpoint} - {self.status_code}"

        
        
# # ---------------------------------------------------------------------------
# # 1. EXAM TYPE — master list: Internal Assessment 1/2, Model Exam,
# #    End Semester, Practical, Assignment...
# # ---------------------------------------------------------------------------
# class ExamType(models.Model):
#     CATEGORY_CHOICES = [("internal", "Internal (CIA)"),("external", "External / End Semester"),("practical", "Practical / Lab"),("model", "Model Exam"),("assignment", "Assignment / Other"),]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="exam_types")
#     name = models.CharField(max_length=100)                       # "Internal Assessment 1"
#     code = models.CharField(max_length=30)                        # "IA1"
#     category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
#     default_max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
#     default_pass_marks = models.DecimalField(max_digits=6, decimal_places=2, default=50)
#     # How much this exam contributes to the final subject total.
#     # e.g. IA1 = 10, IA2 = 10, Model = 20 (internal = 40) ; End Sem = 60
#     weightage = models.DecimalField(max_digits=5, decimal_places=2, default=100,help_text="Contribution to final subject total (out of 100).")
#     is_active = models.BooleanField(default=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["college", "code"], name="unique_exam_type_code_per_college")]
 
#     def __str__(self):
#         return f"{self.name} ({self.code})"
 
 
# # ---------------------------------------------------------------------------
# # 2. EXAM — one exam event for an academic year + semester
# #    (e.g. "End Semester – Nov/Dec 2026", all 3rd-sem students)
# # ---------------------------------------------------------------------------
# class Exam(models.Model):
#     STATUS_CHOICES = [("draft", "Draft"),("registration_open", "Registration Open"),("scheduled", "Scheduled"),("ongoing", "Ongoing"),("marks_entry", "Marks Entry"),("under_review", "Under Review"),("published", "Results Published"),("closed", "Closed"),]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="exams")
#     academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="exams")
#     exam_type = models.ForeignKey(ExamType, on_delete=models.PROTECT, related_name="exams")
#     name = models.CharField(max_length=150)
#     semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES)
#     year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES, null=True, blank=True)
#     departments = models.ManyToManyField(Department, blank=True, related_name="exams",help_text="Leave empty = all departments.")
#     start_date = models.DateField()
#     end_date = models.DateField()
#     registration_open_date = models.DateField(null=True, blank=True)
#     registration_close_date = models.DateField(null=True, blank=True)
#     # Optional exam fee, billed through your existing invoice system
#     fee_category = models.ForeignKey(FeeCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="exams")
#     fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
#     min_attendance_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=75,help_text="Below this = not eligible (unless condoned).")
#     status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
#     result_published_at = models.DateTimeField(null=True, blank=True)
#     created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="exams_created")
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["college", "academic_year", "exam_type", "semester", "name"],
#                                                name="unique_exam_per_year_type_sem_name")]
#         indexes = [models.Index(fields=["college", "academic_year", "status"])]
 
#     def clean(self):
#         if self.start_date and self.end_date and self.start_date > self.end_date:
#             raise ValidationError("Start date must be on or before end date.")
 
#     def __str__(self):
#         return f"{self.name} – {self.academic_year} (Sem {self.semester})"
 
 
# # ---------------------------------------------------------------------------
# # 3. EXAM SCHEDULE — timetable row: which subject, which date/session.
# #    subject_mapping already carries department + year + semester.
# # ---------------------------------------------------------------------------
# class ExamSchedule(models.Model):
#     SESSION_CHOICES = [("FN", "Forenoon"), ("AN", "Afternoon"), ("FULL", "Full Day")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="schedules")
#     subject_mapping = models.ForeignKey(DepartmentSubjectMapping, on_delete=models.PROTECT, related_name="exam_schedules")
#     exam_date = models.DateField()
#     session = models.CharField(max_length=4, choices=SESSION_CHOICES, default="FN")
#     start_time = models.TimeField()
#     end_time = models.TimeField()
#     max_marks = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0)])
#     pass_marks = models.DecimalField(max_digits=6, decimal_places=2, validators=[MinValueValidator(0)])
#     is_practical = models.BooleanField(default=False)
#     is_active = models.BooleanField(default=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["exam", "subject_mapping"], name="unique_subject_per_exam")]
#         indexes = [models.Index(fields=["exam", "exam_date"])]
#         ordering = ["exam_date", "start_time"]
 
#     def clean(self):
#         if self.pass_marks > self.max_marks:
#             raise ValidationError("Pass marks cannot exceed max marks.")
#         if self.start_time and self.end_time and self.start_time >= self.end_time:
#             raise ValidationError("Start time must be before end time.")
 
#     def __str__(self):
#         return f"{self.exam.name} · {self.subject_mapping.subject.code} · {self.exam_date}"
 
 
# # ---------------------------------------------------------------------------
# # 4. EXAM HALL — physical rooms used for exams (separate from Classroom,
# #    which is a class section, not a venue).
# # ---------------------------------------------------------------------------
# class ExamHall(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="exam_halls")
#     name = models.CharField(max_length=100)
#     building = models.CharField(max_length=100, blank=True)
#     capacity = models.PositiveIntegerField()
#     is_active = models.BooleanField(default=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["college", "name"], name="unique_exam_hall_per_college")]
 
#     def __str__(self):
#         return f"{self.name} (cap {self.capacity})"
 
 
# # ---------------------------------------------------------------------------
# # 5. REGISTRATION — one row per student per exam. Holds eligibility
# #    (attendance / fee clearance) and the hall ticket.
# # ---------------------------------------------------------------------------
# class ExamRegistration(models.Model):
#     ELIGIBILITY_CHOICES = [("eligible", "Eligible"),("condoned", "Eligible (Condonation)"),("not_eligible_attendance", "Not Eligible – Attendance"),("not_eligible_fees", "Not Eligible – Fees Due"),("detained", "Detained"),]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="registrations")
#     student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="exam_registrations")
#     enrollment = models.ForeignKey(StudentEnrollment, on_delete=models.PROTECT, null=True, blank=True,related_name="exam_registrations")
#     eligibility = models.CharField(max_length=30, choices=ELIGIBILITY_CHOICES, default="eligible")
#     attendance_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,help_text="Snapshot at registration time.")
#     fee_invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.SET_NULL, null=True, blank=True,related_name="exam_registrations")
#     hall_ticket_number = models.CharField(max_length=40, blank=True)
#     hall_ticket_issued_at = models.DateTimeField(null=True, blank=True)
#     condoned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     remarks = models.CharField(max_length=255, blank=True)
#     registered_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [
#             models.UniqueConstraint(fields=["exam", "student"], name="unique_registration_per_exam_student"),
#             models.UniqueConstraint(fields=["exam", "hall_ticket_number"],condition=models.Q(hall_ticket_number__gt=""),name="unique_hall_ticket_per_exam"),]
#         indexes = [models.Index(fields=["exam", "eligibility"])]
 
#     def __str__(self):
#         return f"{self.student.admission_number} · {self.exam.name}"
 
 
# # ---------------------------------------------------------------------------
# # 6. REGISTRATION SUBJECT — which papers a student writes. Fresh subjects
# #    for the semester + arrear (backlog) subjects from earlier semesters.
# # ---------------------------------------------------------------------------
# class ExamRegistrationSubject(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     registration = models.ForeignKey(ExamRegistration, on_delete=models.PROTECT, related_name="subjects")
#     schedule = models.ForeignKey(ExamSchedule, on_delete=models.PROTECT, related_name="registered_students")
#     is_arrear = models.BooleanField(default=False)
#     attempt_number = models.PositiveSmallIntegerField(default=1)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["registration", "schedule"],name="unique_subject_per_registration")]
 
#     def __str__(self):
#         return f"{self.registration} · {self.schedule.subject_mapping.subject.code}"
 
 
# # ---------------------------------------------------------------------------
# # 7. SEATING ALLOCATION + hall attendance on exam day
# # ---------------------------------------------------------------------------
# class ExamSeatingAllocation(models.Model):
#     ATTENDANCE_CHOICES = [("pending", "Pending"), ("present", "Present"), ("absent", "Absent")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name="seatings")
#     hall = models.ForeignKey(ExamHall, on_delete=models.PROTECT, related_name="seatings")
#     registration_subject = models.OneToOneField(ExamRegistrationSubject, on_delete=models.CASCADE,related_name="seating")
#     seat_number = models.CharField(max_length=20)
#     attendance_status = models.CharField(max_length=10, choices=ATTENDANCE_CHOICES, default="pending")
#     answer_booklet_number = models.CharField(max_length=40, blank=True)
#     marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["schedule", "hall", "seat_number"],
#                                                name="unique_seat_per_hall_schedule")]
#         indexes = [models.Index(fields=["schedule", "hall"])]
 
#     def __str__(self):
#         return f"{self.hall.name} · {self.seat_number}"
 
 
# # ---------------------------------------------------------------------------
# # 8. INVIGILATOR / EXAMINER DUTY
# # ---------------------------------------------------------------------------
# class ExamInvigilator(models.Model):
#     ROLE_CHOICES = [("chief", "Chief Superintendent"),("invigilator", "Invigilator"),("internal_examiner", "Internal Examiner"),("external_examiner", "External Examiner"),]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     schedule = models.ForeignKey(ExamSchedule, on_delete=models.CASCADE, related_name="invigilators")
#     hall = models.ForeignKey(ExamHall, on_delete=models.PROTECT, null=True, blank=True, related_name="invigilators")
#     staff = models.ForeignKey(StaffProfile, on_delete=models.PROTECT, related_name="exam_duties")
#     role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="invigilator")
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["schedule", "staff"], name="unique_staff_per_schedule")]
 
#     def __str__(self):
#         return f"{self.staff} · {self.get_role_display()}"
 
 
# # ---------------------------------------------------------------------------
# # 9. MARKS — one row per student per subject per exam.
# #    Workflow: draft -> submitted (teacher) -> verified (HOD) -> locked (office)
# # ---------------------------------------------------------------------------
# class ExamMark(models.Model):
#     STATUS_CHOICES = [("draft", "Draft"), ("submitted", "Submitted"), ("verified", "Verified"), ("locked", "Locked")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     registration_subject = models.OneToOneField(ExamRegistrationSubject, on_delete=models.PROTECT,related_name="mark")
#     # Denormalised (copied in save) so class-wise mark entry and reports avoid joins
#     schedule = models.ForeignKey(ExamSchedule, on_delete=models.PROTECT, related_name="marks", editable=False)
#     student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="exam_marks", editable=False)
#     academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="exam_marks",editable=False, null=True)
#     marks_obtained = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,validators=[MinValueValidator(0)])
#     grace_marks = models.DecimalField(max_digits=5, decimal_places=2, default=0)
#     is_absent = models.BooleanField(default=False)
#     is_malpractice = models.BooleanField(default=False)
#     status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft", db_index=True)
#     entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     entered_at = models.DateTimeField(null=True, blank=True)
#     verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     verified_at = models.DateTimeField(null=True, blank=True)
#     remarks = models.CharField(max_length=255, blank=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         indexes = [models.Index(fields=["schedule", "status"]), models.Index(fields=["student", "schedule"]),
#                    models.Index(fields=["academic_year", "student"])]
 
#     @property
#     def final_marks(self):
#         if self.is_absent or self.marks_obtained is None:
#             return Decimal("0")
#         return min(self.marks_obtained + self.grace_marks, self.schedule.max_marks)
 
#     @property
#     def is_pass(self):
#         return (not self.is_absent and not self.is_malpractice
#                 and self.marks_obtained is not None
#                 and self.final_marks >= self.schedule.pass_marks)
 
#     def clean(self):
#         if self.marks_obtained is not None and self.marks_obtained > self.schedule.max_marks:
#             raise ValidationError("Marks obtained cannot exceed max marks.")
#         if self.is_absent and self.marks_obtained:
#             raise ValidationError("Absent students cannot have marks.")
 
#     def save(self, *args, **kwargs):
#         rs = self.registration_subject
#         self.schedule_id = rs.schedule_id
#         self.student_id = rs.registration.student_id
#         self.academic_year_id = rs.schedule.exam.academic_year_id
#         super().save(*args, **kwargs)
 
#     def __str__(self):
#         return f"{self.student.admission_number} · {self.schedule.subject_mapping.subject.code} · {self.marks_obtained}"
 
 
# # ---------------------------------------------------------------------------
# # 10. MARK AUDIT LOG — every change after submission must be traceable.
# # ---------------------------------------------------------------------------
# class ExamMarkAudit(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     mark = models.ForeignKey(ExamMark, on_delete=models.CASCADE, related_name="audit_logs")
#     old_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
#     new_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
#     old_status = models.CharField(max_length=10, blank=True)
#     new_status = models.CharField(max_length=10, blank=True)
#     reason = models.CharField(max_length=255, blank=True)
#     changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
#     changed_at = models.DateTimeField(auto_now_add=True)
 
#     class Meta:
#         indexes = [models.Index(fields=["mark", "-changed_at"])]
 
 
# # ---------------------------------------------------------------------------
# # 11. GRADE SCALE — percentage -> letter grade -> grade point
# # ---------------------------------------------------------------------------
# class GradeScale(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     college = models.ForeignKey(College, on_delete=models.CASCADE, related_name="grade_scales")
#     name = models.CharField(max_length=100)
#     is_default = models.BooleanField(default=False)
#     is_active = models.BooleanField(default=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["college"], condition=models.Q(is_default=True),name="unique_default_grade_scale_per_college"),]
 
#     def __str__(self):
#         return self.name
 
 
# class GradeScaleItem(models.Model):
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     scale = models.ForeignKey(GradeScale, on_delete=models.CASCADE, related_name="items")
#     grade = models.CharField(max_length=3)                              # O, A+, A, B+ ... U
#     min_percentage = models.DecimalField(max_digits=5, decimal_places=2)
#     max_percentage = models.DecimalField(max_digits=5, decimal_places=2)
#     grade_point = models.DecimalField(max_digits=4, decimal_places=2)
#     is_pass = models.BooleanField(default=True)
 
#     class Meta:
#         ordering = ["-min_percentage"]
#         constraints = [models.UniqueConstraint(fields=["scale", "grade"], name="unique_grade_per_scale")]
 
#     def __str__(self):
#         return f"{self.grade} ({self.min_percentage}-{self.max_percentage}) = {self.grade_point}"
 
 
# # ---------------------------------------------------------------------------
# # 12. SUBJECT RESULT — consolidated result per subject (internal + external).
# #     One row per attempt, so arrear re-attempts keep history.
# # ---------------------------------------------------------------------------
# class SubjectResult(models.Model):
#     RESULT_CHOICES = [("pass", "Pass"), ("fail", "Fail"), ("absent", "Absent"),("withheld", "Withheld"), ("malpractice", "Malpractice")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="subject_results")
#     subject_mapping = models.ForeignKey(DepartmentSubjectMapping, on_delete=models.PROTECT, related_name="results")
#     academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="subject_results")
#     semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES)
#     attempt_number = models.PositiveSmallIntegerField(default=1)
#     # Snapshots: mapping/subject rows can be edited later; the marksheet must not change.
#     subject_code = models.CharField(max_length=50, blank=True)
#     subject_name = models.CharField(max_length=150, blank=True)
#     internal_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
#     external_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
#     total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=0)
#     max_total_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
#     percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
#     grade = models.CharField(max_length=3, blank=True)
#     grade_point = models.DecimalField(max_digits=4, decimal_places=2, default=0)
#     credits = models.PositiveSmallIntegerField(default=0, help_text="Snapshot of Subject.credits.")
#     credits_earned = models.PositiveSmallIntegerField(default=0)
#     result_status = models.CharField(max_length=12, choices=RESULT_CHOICES)
#     is_arrear = models.BooleanField(default=False)
#     is_published = models.BooleanField(default=False)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(
#             fields=["student", "subject_mapping", "attempt_number"], name="unique_subject_result_per_attempt")]
#         indexes = [models.Index(fields=["student", "academic_year", "semester"]),
#                    models.Index(fields=["subject_mapping", "result_status"])]
 
#     def __str__(self):
#         return f"{self.student.admission_number} · {self.subject_mapping.subject.code} · {self.grade or self.result_status}"
 
 
# # ---------------------------------------------------------------------------
# # 13. SEMESTER RESULT — GPA / CGPA summary printed on the marksheet.
# # ---------------------------------------------------------------------------
# class SemesterResult(models.Model):
#     RESULT_CHOICES = [("pass", "Pass"), ("fail", "Fail (Arrears)"), ("withheld", "Withheld"), ("detained", "Detained")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     student = models.ForeignKey(StudentProfile, on_delete=models.PROTECT, related_name="semester_results")
#     enrollment = models.ForeignKey(StudentEnrollment, on_delete=models.PROTECT, null=True, blank=True,related_name="semester_results")
#     exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="semester_results")
#     academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="semester_results")
#     semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES)
#     department = models.ForeignKey(Department, on_delete=models.PROTECT, null=True, blank=True,related_name="semester_results")
#     year = models.PositiveSmallIntegerField(choices=YEAR_CHOICES, null=True, blank=True)
#     section = models.CharField(max_length=50, blank=True)
#     roll_number = models.CharField(max_length=100, blank=True)
#     credits_registered = models.PositiveSmallIntegerField(default=0)
#     credits_earned = models.PositiveSmallIntegerField(default=0)
#     gpa = models.DecimalField(max_digits=4, decimal_places=2, default=0)
#     cgpa = models.DecimalField(max_digits=4, decimal_places=2, default=0)
#     arrear_count = models.PositiveSmallIntegerField(default=0)
#     result_status = models.CharField(max_length=10, choices=RESULT_CHOICES)
#     is_published = models.BooleanField(default=False)
#     published_at = models.DateTimeField(null=True, blank=True)
#     published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["student", "exam"], name="unique_semester_result_per_exam")]
#         indexes = [models.Index(fields=["exam", "is_published"]),
#                    models.Index(fields=["student", "semester"]),
#                    models.Index(fields=["academic_year", "semester", "department"])]
 
#     def __str__(self):
#         return f"{self.student.admission_number} · Sem {self.semester} · GPA {self.gpa}"
 
 
# # ---------------------------------------------------------------------------
# # 14. REVALUATION / RETOTALING / PHOTOCOPY REQUEST
# # ---------------------------------------------------------------------------
# class RevaluationRequest(models.Model):
#     TYPE_CHOICES = [("photocopy", "Photocopy"), ("retotal", "Re-totaling"), ("revaluation", "Revaluation")]
#     STATUS_CHOICES = [("applied", "Applied"), ("fee_pending", "Fee Pending"), ("in_review", "In Review"),("completed", "Completed"), ("rejected", "Rejected")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     mark = models.ForeignKey(ExamMark, on_delete=models.PROTECT, related_name="revaluation_requests")
#     student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="revaluation_requests")
#     request_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
#     fee_invoice = models.ForeignKey(StudentFeeInvoice, on_delete=models.SET_NULL, null=True, blank=True,related_name="revaluation_requests")
#     status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="applied")
#     old_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
#     new_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
#     reason = models.CharField(max_length=255, blank=True)
#     processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     applied_at = models.DateTimeField(auto_now_add=True)
#     completed_at = models.DateTimeField(null=True, blank=True)
 
#     class Meta:
#         constraints = [models.UniqueConstraint(fields=["mark", "request_type"],condition=~models.Q(status="rejected"),name="unique_active_revaluation_per_mark_type")]
 
#     def __str__(self):
#         return f"{self.get_request_type_display()} · {self.student.admission_number}"
 
 
# # ---------------------------------------------------------------------------
# # 15. MALPRACTICE REPORT
# # ---------------------------------------------------------------------------
# class ExamMalpracticeReport(models.Model):
#     ACTION_CHOICES = [("warning", "Warning"), ("subject_cancelled", "Subject Cancelled"),("exam_cancelled", "Exam Cancelled"), ("suspended", "Suspended"), ("pending", "Pending Inquiry")]
#     id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
#     registration_subject = models.ForeignKey(ExamRegistrationSubject, on_delete=models.PROTECT,related_name="malpractice_reports")
#     reported_by = models.ForeignKey(StaffProfile, on_delete=models.SET_NULL, null=True, related_name="+")
#     description = models.TextField()
#     action_taken = models.CharField(max_length=20, choices=ACTION_CHOICES, default="pending")
#     decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,related_name="+")
#     reported_at = models.DateTimeField(auto_now_add=True)
#     decided_at = models.DateTimeField(null=True, blank=True)