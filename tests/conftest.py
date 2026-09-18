import pytest


@pytest.fixture(autouse=True)
def generic_rekening_labels(monkeypatch):
    monkeypatch.setenv("FINDASH_CC_REKENING", "Rekening A")
    monkeypatch.setenv("FINDASH_OWN_REKENINGEN", "Rekening A,Rekening B")
