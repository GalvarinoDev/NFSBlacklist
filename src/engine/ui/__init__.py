"""
engine.ui - one look and one set of screens for every project

    from engine.ui import app
    app.run()                          # standard flow
    app.run(extra_screens=[MyScreen])  # plus project screens

Screens are registered by class name and navigated with go_to(name),
never by stack index. Brand colours come from identity.THEME.
"""
