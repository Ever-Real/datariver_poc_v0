from datariver.config import get_settings
from datariver.interfaces.http.factory import create_app

app = create_app(get_settings())
