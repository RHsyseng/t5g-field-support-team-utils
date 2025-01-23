from setuptools import find_packages, setup

setup(
    name="t5gweb",
    version="1.250123",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        "flask",
        "gunicorn",
        "jira",
        "requests",
        "slack_sdk",
        "redis",
        "python_bugzilla",
        "celery",
        "flower",
        "python3-saml",
        "flask-login",
        "prometheus-flask-exporter",
        "Werkzeug",
        "xmlsec",
    ],
)
