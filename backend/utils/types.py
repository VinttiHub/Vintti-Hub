def to_bool(value):
    """
    Convert different truthy/falsy representations into bool/None.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    return s in ('1', 'true', 't', 'yes', 'y', '✓', '[v]', 'on')
