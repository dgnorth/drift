from setuptools import find_packages, setup

with open('VERSION') as f:
    version = f.read().strip()


setup(
    name='Drift',
    version=version,
    license='MIT',
    author='Directive Games North',
    author_email='info@directivegames.com',
    description='Micro-framework for SOA based applications',
    packages=find_packages(),
    include_package_data=True,
    scripts=['scripts/drift-admin.py'],
    entry_points={'console_scripts': [
        'drift-admin = drift.management:execute_cmd',
    ]},

    install_requires=[
        'Flask>=1.0.0',
        'Flask-RESTful',  # Will be removed
        'flask-restplus',
        'flask-rest-api',
        'jsonschema',
        'pyopenssl>=17',
        'celery',
        'click', # explicit requirement on the click library for echo and cmdlinge

        # Python 3 compatibility
        'six',

        # Resource module dependencies
        'SQLAlchemy',
        'alembic',
        'psycopg2-binary>=2.7.4',
        'redis',
        'redlock',
        'cryptography',
        'PyJWT',
        'sentry-sdk[flask]',
    ],

    extras_require={
        'aws': [
            'boto',
            'boto3',
            'paramiko',
            'fabric>=2.0',
        ],
        'test': [
            'pytest',
            'pytest-cov',
            'codecov',
            'requests',
            'responses',
            'travispy',
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
        'Programming Language :: Python :: 2.7',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Application Frameworks',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
)
