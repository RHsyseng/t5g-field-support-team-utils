from setuptools import find_packages, setup

setup(
    name="t5gweb",
    version="1.250507",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "celery==5.4.0",
        "Flask==3.1.0",
        "Flask-Login==0.6.3",
        "flower==2.0.1",
        "gunicorn==23.0.0",
        "jira==3.8.0",
        "prometheus_flask_exporter==0.23.1",
        "python-bugzilla==3.3.0",
        "python3-saml==1.16.0",
        "redis==5.2.1",
        "requests==2.32.3",
        "slack_sdk==3.34.0",
        "Werkzeug==3.1.3",
    ],
)
