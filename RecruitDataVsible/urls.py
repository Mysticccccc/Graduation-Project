from django.contrib import admin
from django.urls import include, path

from RecruitDataVsible import settings
from dataView import views


urlpatterns = [
    path("", views.index),
    path("admin/", admin.site.urls),
    path("page/<str:pageName>", views.pageConvert),
    path("job/getJobsInfo", views.getJobInfos),
    path("job/AvgSalaryEveryCity", views.getAvgSalaryEveryCity),
    path("job/jobCountsEveryCity", views.getJobCountsByEveryCity),
    path("job/avgWage", views.getAvgSalaryByCityAndJobType),
    path("job/jobTypeCountOfCity", views.getJobTypeCountByCity),
    path("job/getEducationAndExperienceOfCity", views.getEducationAndExperienceOfCity),
    path("job/onlineSpider", views.onlineSpider),
    path("job/companyInfo", views.companyInfo),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
