class User:
    def __init__(self, user: dict):
        self.id = user.get("id")
        self.type = user.get("type")
        self.roles = user.get("roles")
        self.email = user.get("email")
