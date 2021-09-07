class User:
    def __init__(self, user: dict):
        self._id = user.get("id")
        self._type = user.get("type")
        self._roles = user.get("roles")
        self._email = user.get("email")
