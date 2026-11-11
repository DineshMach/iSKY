"""
URL configuration for iSKY project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from isky_app import views

handler404 = "isky_app.views.custom_404_view"
handler500 = "isky_app.views.custom_500_view"

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # =========================================================
    # NOTE : PLATFORM ADMIN ---------------
    # =========================================================
    
    path("auth/platform/register/", views.create_platform_user_api_view, name="platform-register"),
    path("auth/platform/login/", views.platform_user_login_api_view, name="platform-login"),
    path("auth/email/verify/", views.verify_otp_and_setup, name="email-auth-verification"),
    path('platform/dashboard/', views.platform_dashboard_page,name='platform-dashboard'),
    path("platform/colleges/", views.platform_colleges_page, name="platform-colleges"),
    path('platform/college-users/', views.platform_college_users_page,name='platform-college-users'),
    path("api/platform/colleges/", views.platform_colleges, name="platform-colleges-api"),
    path("api/platform/college-users/", views.platform_college_users, name="platform-college-users-api"),
    
    path("", views.home, name="home"),
    
    # =========================================================
    # NOTE : COLLEGE LEVEL API'S ----------
    # =========================================================
     
     
    # Master Admin
    path("login/admin/", views.admin_login, name="admin_login"),
    path('college/master/admin/dashboard/', views.college_admin_dashboard, name='master-admin-dashboard'),
   
    path('staff/create/', views.create_staff_profile, name='staff-create'),
    path('college/office-admins/list/', views.college_office_admins, name='college-office-admin'),
    path('college/office-admins/create/', views.create_office_admins, name='create-office-admin'),
    path('college/office-admins/<uuid:office_admin_id>/', views.office_admin_detail, name='office-admin-detail'),
    path('college/office-admins/<uuid:office_admin_id>/update/', views.update_office_admin, name='update-office-admin'),

    path('college/departments/list/', views.department_list, name='department-list'),
    path('college/departments/create/', views.department_list_create, name='department-create'),
    path("college/departments/<uuid:department_id>/", views.department_detail, name="department-detail"),
    path("college/departments/<uuid:department_id>/update/", views.update_department, name="update-department"),
    
    path("college/admin/profile/",views.admin_profile_view,name="admin-profile"),
    path("college/admin/panel/settings/", views.admin_settings_view, name="admin-settings"),
    path("college/api/admin/profile/update/",views.admin_profile_update,name="admin-profile-update"),
    path("college/api/admin/password/request-otp/",views.admin_password_request_otp,name="admin-password-request-otp"),
    path("college/api/admin/password/verify-otp/",views.admin_password_verify_otp,name="admin-password-verify-otp"),
    path("college/admin/forgot-password/", views.forgot_password_view, name="forgot-password"),
    path("college/admin/reset-password/",  views.reset_password_view,  name="reset-password"),
    
    path("college/staff/list/", views.staff_list, name="college-staff"),
    # path("api/college-staff/", views.staff_list_api, name="college-staff-api"),
    path("college/create/staff", views.create_staff, name="create-staff"),
    path("staff/bulk-create/", views.bulk_create_staff, name="bulk-create-staff"),
    path("staff/download-sample/", views.download_staff_sample, name="download-staff-sample"),
    path("college/staff/<uuid:staff_id>/deactivate/", views.deactivate_staff, name="deactivate-staff"),
    path('college/staff/<uuid:staff_id>/', views.staff_detail, name='staff-detail'),
    path('college/staff/<uuid:staff_id>/update/', views.update_staff, name='update-staff'),
    path('college/staff/<uuid:staff_id>/update-subjects/', views.update_staff_subjects, name='update-staff-subjects'),
    
    path("college/subjects/", views.subject_list, name="college-subjects"),
    # path("api/college-subjects/", views.subject_list_api, name="college-subjects-api"),
    path("college/create/subject/", views.create_subject, name="create-subject"),
    path("college/subjects/<uuid:subject_id>/", views.subject_detail, name="subject-detail"),
    path("college/subjects/<uuid:subject_id>/update/", views.update_subject, name="update-subject"),
    path("college/subject-mappings/<uuid:mapping_id>/update-teacher/", views.update_subject_mapping_teacher, name="update-subject-mapping-teacher"),
    
    path("college/students/", views.student_list, name="college-students"),
    # path("api/college-students/", views.student_list_api, name="college-students-api"),
    path("college/create/student/", views.create_student, name="create-student"),
    path("students/bulk-create/", views.bulk_create_student, name="bulk-create-student"),
    path("students/sample-download/", views.download_student_sample, name="download-student-sample"),
    path("college/students/<uuid:student_id>/", views.student_detail, name="student-detail"),
    path("college/students/<uuid:student_id>/update/", views.update_student_profile, name="update-student-profile"),
    path("college/student/promotion/", views.student_promotion, name="student-promotion"),
    path("college/students/promote/", views.promote_students, name="promote-students"),
    
    path("enrollment/", views.enroll_students_page, name="enroll-students"),
    path("api/enrollment/classrooms/", views.enrollment_classrooms, name="enrollment-classrooms"),
    path("api/enrollment/students/", views.enrollment_students, name="enrollment-students"),
    path("api/enrollment/save/", views.enrollment_save, name="enrollment-save"),
    path("api/enrollment/candidates/", views.enrollment_candidates, name="enrollment-candidates"),
    
    # Fee Structure And Assign Fees
    
    path("college/fees/", views.fee_list_page, name="fee-management"),
    path("college/fees/student/<uuid:student_id>/", views.fee_student_detail_page, name="fee-student-detail"),
    # JSON API
    path("api/fees/", views.fee_list_api, name="fee-list-api"),
    path("api/fees/students/<uuid:student_id>/", views.fee_student_detail_api, name="fee-student-detail-api"),
    path("api/fees/invoices/<uuid:invoice_id>/", views.fee_invoice_update, name="fee-invoice-update"),
    path("api/fees/payments/<uuid:payment_id>/", views.fee_payment_update, name="fee-payment-update"),
 
    
    path("college/students/fee/structure/create/", views.create_fee_structure_page, name="create-fee-structure-page"),
    path("college/fee/structure/create/", views.create_fee_structure_api, name="api-create-fee-structure"),
    path("college/fee/structure/", views.fee_structure_list_api, name="api-fee-structure-list"),
    path("college/fee/categories/", views.fee_categories_api, name="api-fee-categories"),
    path("college/fee/structures/assign/",views.assign_fee_structure_page,name="assign-fee-structure-page",),
    path("college/fee/structures/<uuid:fee_structure_id>/eligible/students/",views.eligible_students,name="api-eligible-students",),
    path("college/assign/fee/structure/",views.assign_fee_structure,name="api-assign-fee-structure",),
    path("colleges/<uuid:college_id>/fee-categories/",views.fee_category_list,name="api-fee-categories",),
    path("colleges/fee/structures/<uuid:pk>/",views.fee_structure_detail,name="api-fee-structure-detail",),
    
    path("colleges/fees/bulk-invoices/", views.bulk_invoice_page, name="bulk-fee-invoices"),
    path("colleges/fees/students/search/", views.student_search, name="student-search"),
    path("colleges/fees/bulk-invoices/preview/", views.bulk_invoice_preview, name="bulk-invoice-preview"),
    path("colleges/fees/bulk-invoices/generate/", views.bulk_invoice_generate, name="bulk-invoice-generate"),
    path("colleges/fees/bulk-invoices/", views.bulk_invoice_list, name="bulk-invoice-list"),
    path("colleges/fees/bulk-invoices/<uuid:batch_id>/", views.bulk_invoice_detail, name="bulk-invoice-detail"), 
    
    # path("colleges/fees/payments/", views.fee_payment_history_page, name="fee-payment-history-page"),
    # path("api/fees/payments/", views.fee_payment_list, name="fee-payment-list"),
    # path("api/fees/payments/<uuid:payment_id>/", views.fee_payment_detail, name="fee-payment-detail"),
    # path("api/fees/payments/<uuid:payment_id>/convert-to-offline/", views.fee_payment_convert_to_offline, name="fee-payment-convert-offline"),
    # path("colleges/fee/structures/<uuid:fee_structure_id>/items/",views.fee_structure_item_list,name="api-fee-structure-items",),
    # path("colleges/fee/structures/<uuid:fee_structure_id>/items/summary/",views.fee_structure_items_summary,name="api-fee-structure-items-summary",),
    # path("colleges/fee/structure/items/<uuid:pk>/",views.fee_structure_item_detail,name="api-fee-structure-item-detail",),
    # path("colleges/fee/structure/items/bulk/create/",views.fee_structure_item_bulk_create,name="api-fee-structure-items-bulk-create",),
    
    path("college/fee/transactions/", views.admin_fee_transactions_page, name="admin-fee-transactions-page"),
    path("college/fee/settlements/", views.admin_settlement_batches_page, name="admin-settlement-batches-page"),
    path("college/fee/settlements/<uuid:batch_id>/",views.admin_settlement_batch_detail_page,name="admin-settlement-batch-detail-page",),
    path("college/admin/fee/structures/", views.fee_structure_list_page, name="fee-structure-list-page"),
    path("college/admin/fee/structures/<uuid:structure_id>/",views.fee_structure_detail_page,name="fee-structure-detail-page",),
    
    path("college/fees/invoices/", views.invoice_history_page, name="invoice-history-page"),
    path("college/api/fees/invoices/", views.invoice_list, name="invoice-list"),
    path("college/api/fees/invoices/<uuid:invoice_id>/", views.invoice_detail, name="invoice-detail"),
    path("college/api/fees/invoices/<uuid:invoice_id>/record-offline-payment/", views.invoice_record_offline_payment, name="invoice-record-offline-payment"),
    path("college/api/fees/invoices/<uuid:invoice_id>/override-status/", views.invoice_override_status, name="invoice-override-status"),
    
    path("college/fees/offline-collections/", views.offline_collection_history_page, name="offline-collection-history-page"),
    path("college/api/fees/offline-collections/", views.offline_collection_list, name="offline-collection-list"),
    path("college/api/fees/offline-collections/<uuid:payment_id>/mark-cleared/", views.mark_offline_payment_cleared, name="offline-collection-mark-cleared"),
    
    # Classrooms and Timetable Management
    path("college/classrooms/", views.classroom_list, name="college-classrooms"),
    path("college/create/classroom/", views.create_classroom, name="create-classroom"),
    path("college/classroom/timetable/", views.timetable, name="classroom-timetable"),
    
    path("classrooms/<uuid:classroom_id>/", views.classroom_detail, name="classroom-detail"),
    path("classrooms/<uuid:classroom_id>/update/", views.update_classroom, name="update-classroom"),
    path("classrooms/<uuid:classroom_id>/subjects/<uuid:mapping_id>/teacher/",views.assign_classroom_subject_teacher, name="assign-classroom-subject-teacher"),
    
    path("college/classroom/create/timetable/", views.create_timetable_slot, name="create-timetable-slot"),
    path("college/classroom/timetable/save-grid/", views.save_timetable_grid, name="save-timetable-grid"),
    path("college/classroom/attendance/", views.attendance_select, name="classroom-attendance-select"),
    path("college/classroom/attendance/take/", views.take_attendance, name="classroom-take-attendance"),
    path("college/classroom/attendance/save/", views.save_attendance, name="classroom-save-attendance"),
    

    
    # Staff Admin
    path("login/staff/", views.staff_login, name="staff_login"),
    path("staff/update/password/", views.staff_update_password, name="update_password"),
    path("auth/admin/login/", views.login_api_view, name="college-admin-login"),
    path("auth/admin/logout/",views.logout_view,name="college-admin-logout"),
    path("authentication/error/",views.authentication_error_view,name="authentication-error",),
    
    
    
    # College URLs
    path("colleges/", views.college_list_create_api_view, name="college-list-create"),
    path("colleges/<uuid:pk>/", views.college_detail_api_view, name="college-detail"),

    # College Admin URL
    path("colleges/create-admin/", views.create_college_admin_api_view, name="college-create-admin"),
    
    # Students URLS
    path("college/student/login/", views.student_login_api_view, name="student_login"),
    path("college/student/dashboard/", views.student_dashboard, name="student-dashboard"),
    path("college/student/attendance/", views.attendance_page, name="student-attendance"),
    path("college/student/attendance/summary/", views.attendance_summary, name="api-student-attendance-summary"),
    path("college/student/attendance/subjects/", views.subject_attendance, name="api-student-attendance-subjects"),
    path("college/student/attendance/calendar/", views.attendance_calendar, name="api-student-attendance-calendar"),
    path("college/student/timetable/", views.student_timetable_view, name="student-timetable"),
    path("college/student/profile/", views.student_profile_view, name="student-profile"),
    path("college/student/profile/password/request-otp/", views.request_password_change_otp, name="student-password-request-otp"),
    path("college/student/profile/password/verify-otp/", views.verify_password_change_otp, name="student-password-verify-otp"),
    #Pay Fees
    path("college/student/fee/invoices/", views.student_fee_invoices_page, name="student-fee-invoices-page"),
    path("college/student/fee/invoices/<uuid:invoice_id>/",views.student_fee_invoice_detail_page,name="student-fee-invoice-detail-page",),
    # API
    path("api/my/fee/invoices/", views.api_student_fee_invoices, name="api-student-fee-invoices"),
    path("api/my/fee/invoices/<uuid:invoice_id>/",views.api_student_fee_invoice_detail,name="api-student-fee-invoice-detail",),
    path("api/my/fee/invoices/<uuid:invoice_id>/pay/",views.api_pay_invoice,name="api-pay-invoice",),
    # Pages — payment flow
    path("college/fee/invoices/<uuid:invoice_id>/pay/summary/<str:transaction_id>/",views.student_payment_summary_page,name="student-payment-summary-page",),
    path("pay/gateway/<str:transaction_id>/",views.payment_gateway_mock_page,name="payment-gateway-mock-page",),
    # API — invoices
    # API — payment flow
    path("api/my/fee/invoices/<uuid:invoice_id>/pay/initiate/",views.api_initiate_payment,name="api-initiate-payment",),
    path("api/payments/gateway/<str:transaction_id>/callback/",views.api_gateway_callback,name="api-gateway-callback",),
    
]
