from flask import Blueprint

bp = Blueprint('system', __name__)


@bp.route('/')
def home():
    return 'API running 🎉'
