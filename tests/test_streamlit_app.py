from streamlit.testing.v1 import AppTest


def test_streamlit_frontend_renders_safe_configuration_state() -> None:
    app = AppTest.from_file("streamlit_app.py", default_timeout=10)
    app.run()

    assert not app.exception
    assert app.title[0].value == "Railwatch"
    assert app.warning[0].value == (
        "Railwatch is ready, but its server configuration is incomplete."
    )
