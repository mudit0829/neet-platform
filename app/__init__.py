from flask import Flask
from config import Config
from .extensions import db, migrate, login_manager


def seed_defaults():
    from .models import Subject, Chapter

    if Subject.query.count() == 0:
        biology = Subject(name="Biology")
        chemistry = Subject(name="Chemistry")
        physics = Subject(name="Physics")
        db.session.add_all([biology, chemistry, physics])
        db.session.flush()

        db.session.add_all([
            Chapter(subject_id=biology.id, name="Cell: The Unit of Life"),
            Chapter(subject_id=biology.id, name="Biomolecules"),
            Chapter(subject_id=chemistry.id, name="Atomic Structure"),
            Chapter(subject_id=chemistry.id, name="Chemical Bonding"),
            Chapter(subject_id=physics.id, name="Units and Measurements"),
            Chapter(subject_id=physics.id, name="Kinematics"),
        ])
        db.session.commit()


def create_app():
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(Config)

    import os

    app.config["EXPLAIN_TEMPLATE_LOADING"] = True

    print("APP ROOT PATH =", app.root_path)
    print("TEMPLATE FOLDER =", app.template_folder)
    print("STATIC FOLDER =", app.static_folder)
    print("STATIC URL PATH =", app.static_url_path)
    print("CSS app.css exists =", os.path.exists(os.path.join(app.static_folder, "css", "app.css")))
    print("CSS style.css exists =", os.path.exists(os.path.join(app.static_folder, "css", "style.css")))

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    with app.app_context():
        db.create_all()
        seed_defaults()

    return app
