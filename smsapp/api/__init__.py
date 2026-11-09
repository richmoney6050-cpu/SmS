def register_blueprints(app):
    from . import attendance, auth, command, exams, extras, register, report_cards, reports, setup, student_tools, students, users

    for bp in (auth.bp, users.bp, setup.bp, students.bp, student_tools.bp, register.bp, attendance.bp, exams.bp, report_cards.bp, reports.bp, extras.bp, command.bp, command.teacher_bp):
        app.register_blueprint(bp)
