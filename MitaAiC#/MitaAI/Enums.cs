﻿namespace MitaAI
{
    public enum character
    {
        // НПС должны строго соотвествовать эквивалентам в питоне!

        Player = -2,
        None = -1,
        Crazy = 0,
        Cappy = 1,
        Kind = 2,
        Cart_portal = 3,
        ShortHair = 4,
        Cart_divan,
        Mila,
        Sleepy,
        Creepy,
        GameMaster

    }
    public enum MovementStyles
    {
        walkNear = 0,
        follow = 1,
        stay = 2,
        noclip = 3,
        layingOnTheFloorAsDead = 4,
        sitting,
        cryingOnTheFloor

    }
    public enum MitaState
    {
        normal = 0,
        hunt = 1

    }

    public enum Rooms
    {
        Kitchen = 0,
        MainHall = 1,
        Bedroom = 2,
        Toilet = 3,
        Basement = 4,
        Unknown = -1
    }

}
