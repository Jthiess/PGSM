import warnings
warnings.filterwarnings('ignore', message='.*Eventlet is deprecated.*')

import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=app.config['FLASK_PORT'], debug=False)
