"""Walk the wrappers `create_adapter` puts around a raw adapter."""


def chain(adapter):
    """The adapter, then each adapter inside it, outermost first, down to the raw one."""
    links = [adapter]
    while hasattr(links[-1], "inner"):
        links.append(links[-1].inner)
    return links


def raw(adapter):
    """The raw adapter at the bottom of the chain (the one that talks to a provider)."""
    return chain(adapter)[-1]


def names(adapter):
    return [type(link).__name__ for link in chain(adapter)]
