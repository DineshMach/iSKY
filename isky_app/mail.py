import logging
from datetime import timedelta
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone
from django.utils.html import escape
from django.conf import settings
logger = logging.getLogger(__name__)


OTP_VALID_MINUTES = 10


def _send_otp_email(user, code, valid_minutes=OTP_VALID_MINUTES):
    subject = 'ISKY ERP — Your Verification Code'
    from_email = 'support@machpay.in'
    to_email = [user.email]#["dinesh.c@machpay.in"]#[user.email]
    expires_at = (timezone.localtime(timezone.now() + timedelta(minutes=valid_minutes)).strftime("%I:%M %p"))
    staff_name = user.first_name or user.email
    # Plain text version (fallback)
    text_content = (
        f"Dear {staff_name},\n\n"
        f"Use the code below to verify your identity and continue setting up your password.\n\n"
        f"Email: {user.email}\n"
        f"Verification Code: {code}\n"
        f"Valid Until: {expires_at} (expires in {valid_minutes} minutes)\n\n"
        f"If you did not request this code, please contact the IT Helpdesk at support@college.edu.\n\n"
        f"Best regards,\n"
        f"College Administration Team"
    )
    # HTML version (styled for readability)
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #1A365D; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px;">
            Verify Your Identity
        </h2>
        <p>Dear <strong>{staff_name}</strong>,</p>
        <p>Use the one-time code below to verify your identity and continue setting up your password.</p>
        <div style="background-color: #F7FAFC; border-left: 4px solid #2B6CB0; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0;">
            <p style="margin: 0 0 8px 0;"><strong>Email:</strong> {user.email}</p>
            <p style="margin: 0 0 8px 0;"><strong>Verification Code:</strong>
                <code style="background: #EDF2F7; padding: 3px 10px; border-radius: 4px; font-size: 1.3em; letter-spacing: 3px; color: #2C5282;">{code}</code>
            </p>
            <p style="margin: 0; font-size: 0.9em; color: #718096;">Valid until {expires_at} ({valid_minutes} minutes from now)</p>
        </div>
        <p style="color: #C53030; font-weight: bold; background-color: #FFF5F5; padding: 10px; border-radius: 4px;">
            ⚠️ Security Notice: Do not share this code with anyone, including college staff.
        </p>
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. If you did not request this code, please notify the IT Administration office immediately at <a href="mailto:support@college.edu" style="color: #2B6CB0;">support@college.edu</a>.
        </p>
    </div>
    """
    message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    message.attach_alternative(html_content, "text/html")
    message.send()

def staff_create_account(staff_name, staff_email, temporary_password, login_url="http://192.168.1.22"):
    subject = 'Welcome to College Staff Portal — Temporary Password'
    from_email = 'support@machpay.in'
    to_email = [staff_email]#[user.email]
    
    # Plain text version (fallback)
    text_content = (
        f"Dear {staff_name},\n\n"
        f"Your college staff account has been created successfully.\n\n"
        f"Login Credentials:\n"
        f"Email: {staff_email}\n"
        f"Temporary Password: {temporary_password}\n\n"
        f"Important: Please log in and update your password immediately after your first sign-in for security reasons.\n\n"
        f"Login Portal: {login_url}\n\n"
        f"If you did not request this account or need technical assistance, please contact the IT Helpdesk at support@college.edu.\n\n"
        f"Best regards,\n"
        f"College Administration Team"
    )
    
    # HTML version (styled for readability)
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #1A365D; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px;">
            Welcome to the College Staff Portal
        </h2>
        <p>Dear <strong>{staff_name}</strong>,</p>
        <p>Your institutional staff account has been created successfully. Below are your temporary credentials to access the portal:</p>
        
        <div style="background-color: #F7FAFC; border-left: 4px solid #2B6CB0; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0;">
            <p style="margin: 0 0 8px 0;"><strong>Username / Email:</strong> {staff_email}</p>
            <p style="margin: 0;"><strong>Temporary Password:</strong> <code style="background: #EDF2F7; padding: 3px 8px; border-radius: 4px; font-size: 1.1em; color: #2C5282;">{temporary_password}</code></p>
        </div>
        
        <p style="color: #C53030; font-weight: bold; background-color: #FFF5F5; padding: 10px; border-radius: 4px;">
            ⚠️ Security Notice: You are required to update your temporary password upon logging in for the first time.
        </p>
        
        <div style="margin: 25px 0;">
            <a href="{login_url}" style="background-color: #2B6CB0; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">Log In to Staff Portal</a>
        </div>
        
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. If you did not expect this account setup, please notify the IT Administration office immediately at <a href="mailto:support@college.edu" style="color: #2B6CB0;">support@college.edu</a>.
        </p>
    </div>
    """
    
    # Send email
    message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    message.attach_alternative(html_content, "text/html")
    message.send()

def student_create_account(student_name,student_email,temporary_password,admission_number="",login_url="http://192.168.1.22/college/student/login/",):
    subject = "Welcome to College Student Portal — Account Setup & Temporary Password"
    from_email = "support@machpay.in"
    to_email = [student_email]  # Replaced hardcoded email with student_email
    admission_info_text = (f"Admission Number: {admission_number}\n" if admission_number else "")
    admission_info_html = (f'<p style="margin: 0 0 8px 0;"><strong>Admission Number:</strong> {admission_number}</p>' if admission_number else "")

    # Plain text version (fallback)
    text_content = (
        f"Dear {student_name},\n\n"
        f"Welcome to the College family! Your student portal account has been set up successfully.\n\n"
        f"Login Credentials:\n"
        f"{admission_info_text}"
        f"Email / Username: {student_email}\n"
        f"Temporary Password: {temporary_password}\n\n"
        f"Important: For security reasons, you will be prompted to verify your email and set a new password upon your first sign-in.\n\n"
        f"Access Student Portal: {login_url}\n\n"
        f"If you have questions or face issues logging in, please contact the Academic IT Support at support@college.edu.\n\n"
        f"Best regards,\n"
        f"Office of Academic Affairs & Administration"
    )

    # HTML version (styled for readability)
    html_content = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #2C5282; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px; margin-top: 0;">
            Welcome to the Student Portal
        </h2>
        <p>Dear <strong>{student_name}</strong>,</p>
        <p>Welcome to the college! Your official student account has been created successfully. Below are your temporary credentials to access the portal:</p>
        
        <div style="background-color: #F7FAFC; border-left: 4px solid #3182CE; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0;">
            {admission_info_html}
            <p style="margin: 0 0 8px 0;"><strong>Username / Email:</strong> {student_email}</p>
            <p style="margin: 0;"><strong>Temporary Password:</strong> <code style="background: #EDF2F7; padding: 3px 8px; border-radius: 4px; font-size: 1.1em; color: #2B6CB0; font-weight: bold;">{temporary_password}</code></p>
        </div>
        
        <div style="background-color: #EBF8FF; border: 1px solid #BEE3F8; padding: 12px; border-radius: 6px; margin-bottom: 20px;">
            <p style="margin: 0; color: #2B6CB0; font-size: 0.95em;">
                🔑 <strong>First-Time Security Setup:</strong> When you log in for the first time, you will be required to verify an OTP and set up a new password.
            </p>
        </div>
        
        <div style="margin: 25px 0;">
            <a href="{login_url}" style="background-color: #3182CE; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">Log In to Student Portal</a>
        </div>
        
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. If you believe this account was created in error, please contact the IT Helpdesk at <a href="mailto:support@college.edu" style="color: #3182CE;">support@college.edu</a>.
        </p>
    </div>
    """

    # Send email
    message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    message.attach_alternative(html_content, "text/html")
    message.send() 
    
def _send_welcome_email(user, login_url="http:192.168.1.22"):
    subject = 'Welcome to ISKY ERP — Account Activated'
    from_email = 'support@machpay.in'
    to_email = [user.email]#[user.email]

    staff_name = user.first_name or user.email

    text_content = (
        f"Dear {staff_name},\n\n"
        f"Your password has been set successfully and your account is now fully active.\n\n"
        f"Email: {user.email}\n\n"
        f"You can sign in anytime using your Staff ID and new password.\n\n"
        f"Login Portal: {login_url}\n\n"
        f"If you did not make this change, please contact the IT Helpdesk immediately at support@college.edu.\n\n"
        f"Best regards,\n"
        f"College Administration Team"
    )

    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #1A365D; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px;">
            Account Activated
        </h2>
        <p>Dear <strong>{staff_name}</strong>,</p>
        <p>Your password has been set successfully and your account is now fully active.</p>
        <div style="background-color: #F7FAFC; border-left: 4px solid #2B6CB0; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0;">
            <p style="margin: 0;"><strong>Email:</strong> {user.email}</p>
        </div>
        <div style="margin: 25px 0;">
            <a href="{login_url}" style="background-color: #2B6CB0; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">Go to Staff Portal</a>
        </div>
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. If you did not make this change, please notify the IT Administration office immediately at <a href="mailto:support@college.edu" style="color: #2B6CB0;">support@college.edu</a>.
        </p>
    </div>
    """

    message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    message.attach_alternative(html_content, "text/html")
    message.send()
    
def send_password_reset_otp_email(user_name, user_email, otp, expires_in_minutes=10):
    print('test')
    subject = 'Your Password Reset OTP — College Staff Portal'
    from_email = 'support@machpay.in'
    to_email = [user_email]

    # Plain text version (fallback)
    text_content = (
        f"Dear {user_name},\n\n"
        f"We received a request to change your account password.\n\n"
        f"Your One-Time Password (OTP) is: {otp}\n\n"
        f"This code is valid for {expires_in_minutes} minutes. Do not share this code with anyone.\n\n"
        f"If you did not request this change, please ignore this email or contact the IT Helpdesk at support@college.edu.\n\n"
        f"Best regards,\n"
        f"College Administration Team"
    )

    # HTML version (styled for readability)
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #1A365D; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px;">
            Password Reset Request
        </h2>
        <p>Dear <strong>{user_name}</strong>,</p>
        <p>We received a request to change the password on your account. Use the OTP below to confirm this change:</p>
        <div style="background-color: #F7FAFC; border-left: 4px solid #2B6CB0; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0; text-align: center;">
            <p style="margin: 0 0 6px 0; font-size: 0.85em; color: #718096; text-transform: uppercase; letter-spacing: 0.05em;">One-Time Password</p>
            <p style="margin: 0; font-size: 1.8em; font-weight: bold; letter-spacing: 0.15em; color: #2C5282;">{otp}</p>
        </div>
        <p style="color: #C53030; font-weight: bold; background-color: #FFF5F5; padding: 10px; border-radius: 4px;">
            ⚠️ This code expires in {expires_in_minutes} minutes. Do not share it with anyone.
        </p>
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. If you did not request this change, please notify the IT Administration office immediately at <a href="mailto:support@college.edu" style="color: #2B6CB0;">support@college.edu</a>.
        </p>
    </div>
    """

    message = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    message.attach_alternative(html_content, "text/html")
    try:
        # returns 1 if email was sent successfully
        sent_count = message.send(fail_silently=False)
        if sent_count > 0:
            print("Mail sent successfully!")
            return {"status": True, "message": "Email sent successfully."}
        else:
            print("Mail failed to send.")
            return {"status": False, "message": "Failed to send email."}

    except Exception as e:
        print(f"Error sending email: {e}")
        return {"status": False, "message": f"Email sending failed: {str(e)}"}
    print("befor send")
    message.send()
    print("after send")
    
    

SUPPORT_EMAIL = "support@machpay.in"  # or settings.SUPPORT_EMAIL


def common_send_otp_email(*,user,otp,expires_in_minutes,subject,heading,intro_text,ignore_text,):
    user_name = user.get_full_name() or user.get_username()
    safe_name = escape(user_name)
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)

    # Plain text fallback
    text_content = (
        f"Dear {user_name},\n\n"
        f"{intro_text}\n\n"
        f"Your One-Time Password (OTP) is: {otp}\n\n"
        f"This code is valid for {expires_in_minutes} minutes. "
        f"Do not share this code with anyone.\n\n"
        f"{ignore_text} You can also contact the IT Helpdesk at {SUPPORT_EMAIL}.\n\n"
        f"Best regards,\n"
        f"College Administration Team"
    )

    # HTML version
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; color: #2D3748; line-height: 1.6;">
        <h2 style="color: #1A365D; border-bottom: 2px solid #E2E8F0; padding-bottom: 10px;">
            {heading}
        </h2>
        <p>Dear <strong>{safe_name}</strong>,</p>
        <p>{intro_text}</p>
        <div style="background-color: #F7FAFC; border-left: 4px solid #2B6CB0; padding: 15px; margin: 20px 0; border-radius: 0 4px 4px 0; text-align: center;">
            <p style="margin: 0 0 6px 0; font-size: 0.85em; color: #718096; text-transform: uppercase; letter-spacing: 0.05em;">One-Time Password</p>
            <p style="margin: 0; font-size: 1.8em; font-weight: bold; letter-spacing: 0.15em; color: #2C5282;">{otp}</p>
        </div>
        <p style="color: #C53030; font-weight: bold; background-color: #FFF5F5; padding: 10px; border-radius: 4px;">
            ⚠️ This code expires in {expires_in_minutes} minutes. Do not share it with anyone.
        </p>
        <hr style="border: none; border-top: 1px solid #E2E8F0; margin: 30px 0;" />
        <p style="font-size: 0.85em; color: #718096;">
            This is an automated message. {ignore_text} You can also reach the IT Administration office at
            <a href="mailto:{SUPPORT_EMAIL}" style="color: #2B6CB0;">{SUPPORT_EMAIL}</a>.
        </p>
    </div>
    """

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_content,
        from_email=from_email,
        to=[user.email],
    )
    message.attach_alternative(html_content, "text/html")

    try:
        sent_count = message.send(fail_silently=False)
    except Exception:
        logger.exception("Failed to send OTP email (%s) to user_id=%s", subject, user.pk)
        return {"status": False, "message": "Email sending failed."}

    if sent_count > 0:
        return {"status": True, "message": "Email sent successfully."}

    logger.warning("OTP email (%s) not sent for user_id=%s", subject, user.pk)
    return {"status": False, "message": "Failed to send email."}


def send_password_change_otp_email(user, otp, expires_in_minutes=10):
    return common_send_otp_email(
        user=user,
        otp=otp,
        expires_in_minutes=expires_in_minutes,
        subject="Your Password Change Code — College Staff Portal",
        heading="Password Change Request",
        intro_text=(
            "We received a request to change the password on your account. "
            "Use the OTP below to confirm this change:"
        ),
        ignore_text=(
            "If you did not request this change, please ignore this email "
            "and notify the IT Administration office immediately."
        ),)


def send_login_verification_otp_email(user, otp, expires_in_minutes=5):
    return common_send_otp_email(
        user=user,
        otp=otp,
        expires_in_minutes=expires_in_minutes,
        subject="New Login Verification — College Staff Portal",
        heading="New Login Verification",
        intro_text=(
            "We detected a new sign-in attempt on your account. "
            "Use the OTP below to verify it's you:"
        ),
        ignore_text=(
            "If you did not try to sign in, please ignore this email, "
            "change your password, and notify the IT Administration office immediately."
        ),
    )
    

    
# send_password_reset_otp_email(user_name="Test User",user_email="devasurya146@gmail.com",otp="123456",expires_in_minutes=10)