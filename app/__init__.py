from flask import Flask
from config import Config
from .extensions import db, migrate, login_manager


def create_app():
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="../templates",
        static_folder="static",
    )
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    from .routes.main import main_bp
    from .routes.auth import auth_bp
    from .routes.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)

    @app.cli.command("seed")
    def seed():
        from .models import Institute, User, Subject, Chapter

        if not Institute.query.first():
            institute = Institute(name="Demo NEET Institute", slug="demo-neet-institute")
            db.session.add(institute)
            db.session.flush()

            admin = User(
                institute_id=institute.id,
                full_name="Admin User",
                email="admin@example.com",
                role="institute_admin",
            )
            admin.set_password("admin123")

            teacher = User(
                institute_id=institute.id,
                full_name="Teacher User",
                email="teacher@example.com",
                role="teacher",
            )
            teacher.set_password("teacher123")

            student = User(
                institute_id=institute.id,
                full_name="Student User",
                email="student@example.com",
                role="student",
            )
            student.set_password("student123")

            db.session.add_all([admin, teacher, student])

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
            print("Seed data added.")
        else:
            print("Seed skipped: data already exists.")

    return app
