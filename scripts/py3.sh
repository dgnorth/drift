
# switch to python 2
pipenv --rm
rm Pipfile
rm Pipfile.lock
find . -name "*.pyc" -exec rm "{}" ";"
pipenv --three
pipenv install --dev -e "../drift-config[s3-backend,redis-backend]" ".[aws,test]"
