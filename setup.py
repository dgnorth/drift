import os
from setuptools import setup, find_packages

version_file = os.path.abspath(os.path.join("drift", "VERSION"))

with open(version_file) as f:
    version = f.readlines()[0].strip()

setup(
    name='python-drift',
    version=version,
    license='MIT',
    author='Directive Games',
    author_email='info@directivegames.com',
    description='Micro-framework for SOA based applications',
    packages=find_packages(),
    url="https://github.com/dgnorth/drift",
    include_package_data=True,
    scripts=[
        'scripts/drift-admin.py',
        'scripts/sls-deploy.py',
    ],
    entry_points={'console_scripts': [
        'drift-admin = drift.management:execute_cmd',
    ]},

    install_requires=[
        'python-driftconfig',
        'Flask',
        'flask-smorest',
        'flask_marshmallow',
        'jsonschema',
        'pyopenssl>=17',
        'click',  # explicit requirement on the click library for echo and cmdlinge

        # Python 3 compatibility
        'six',

        # Resource module dependencies
        'SQLAlchemy',
        'Flask-SQLAlchemy',
        'marshmallow-sqlalchemy',
        'alembic',
        'psycopg2-binary>=2.7.4',
        'redis',
        'cryptography',
        'PyJWT',
        'logstash_formatter',
        'sentry-sdk[flask]',
        'blinker',
        'pytz',
    ],

    extras_require={
        'aws': [
            'boto3',
            'paramiko',
            'fabric>=2.0',
            'pyyaml',
        ],
        'test': [
            'pytest>=5.0',
            'pytest-cov',
            'codecov',
            'requests',
            'responses',
        ],
    },

    zip_safe=False,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'Framework :: Flask',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
