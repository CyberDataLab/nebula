def test_import_nebula():
    try:
        import nebula
    except ImportError:
        assert False, "Failed to import nebula"
