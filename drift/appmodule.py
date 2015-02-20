# the real app
from flaskfactory import create_app, install_extras

app = create_app()
install_extras(app)