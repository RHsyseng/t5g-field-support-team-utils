from setuptools import find_packages, setup

setup(
    name='t5gweb',
    version='0.210603',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'flask==2.0.2',
        'matplotlib==3.4.3',
        'gunicorn==20.1.0',
        'jira==3.1.1',
        'requests==2.26.0',
        'slack_sdk==3.11.2',
        'flask_apscheduler==1.12.2',
        'redis'
    ],
)
