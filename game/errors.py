class GameError(Exception):
    """A rule of the game was not respected. The message is shown to the player.

    Raising it inside `Database.run` also rolls back the whole transaction.
    """
