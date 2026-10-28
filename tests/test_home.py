def test_home_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "Nurse.ng" in response.text
    assert "public nursing community" in response.text


def test_home_carries_the_regulator_disclaimer(client):
    response = client.get("/")

    assert "Nursing and Midwifery Council of Nigeria" in response.text
    assert "does not replace the official register" in response.text
