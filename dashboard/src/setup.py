from setuptools import find_packages, setup

setup(
    name='t5gweb',
    version='0.210603',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=[
        'flask',
        'matplotlib',
        'gunicorn',
        'jira',
        'requests',
        'slack_sdk',
        'flask_apscheduler'
    ],
)
