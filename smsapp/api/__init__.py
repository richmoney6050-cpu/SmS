def register_blueprints(app):
    from . import attendance, auth, command, exams, register, reports, setup, student_tools, students, users

    for bp in (auth.bp, users.bp, setup.bp, students.bp, student_tools.bp, register.bp, attendance.bp, exams.bp, reports.bp, command.bp, command.teacher_bp):
        app.register_blueprint(bp)
