"""Request models.

Responses are plain dictionaries: directory objects carry whatever the schema
of the domain says they do, and pinning that into response models would mean
maintaining a second copy of Active Directory's schema. Requests are strict,
because that is where bad input has to be stopped.
"""
