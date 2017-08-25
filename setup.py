import sys
from setuptools import find_packages, setup

with open("VERSION") as f:
    version = f.read().strip()

EXCLUDE_FROM_PACKAGES = []


install_requires=[
        "Flask",
        "Flask-Cache",
        "Flask-JWT",
        "Flask-RESTful",
        "requests",
        "python-dateutil",
        "jsonschema",
        "boto",
        "boto3",
        "oss2",
        "redis",
        "celery",
        "responses",
        "SQLAlchemy",
        "paramiko==1.15.2",
        "fabric",
        "colorama",
        "slacker",
        "pycrypto",
        "pyopenssl",
        "cryptography",
        "redlock",
        "alembic",
        ]

tests_require = [
    'mock',
    'nose2',
    'Flask-Testing',
    "coverage",
    ]


setup(
    name='Drift',
    version=version,
    license='MIT',
    author='Directive Games North',
    author_email="info@directivegames.com",
    description='Micro-framework for SOA based applications',
    test_suite="nose2.collector.collector",
    packages=find_packages(exclude=EXCLUDE_FROM_PACKAGES),
    include_package_data=True,
    scripts=['scripts/drift-admin.py'],
    entry_points={'console_scripts': [
        'drift-admin = drift.management:execute_cmd',
    ]},
    install_requires=install_requires + tests_require,
    tests_require=tests_require,
    extras_require={},
    zip_safe=False,
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
