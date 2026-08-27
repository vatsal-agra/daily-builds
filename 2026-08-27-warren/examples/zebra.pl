% The Zebra Puzzle (Life International, 1962) -- the classic Prolog
% constraint-logic demo. Five houses in a row, each with a distinct
% nationality/color/drink/cigarette/pet; 14 clues pin down a UNIQUE
% assignment. The published answer: the Japanese owns the zebra, and
% the Norwegian drinks water.
%
% Each house is a term house(Nationality, Color, Drink, Cigarette, Pet).
% `right_of(R, L, Street)` means R is immediately right of L in the list.

right_of(R, L, [L, R|_]).
right_of(R, L, [_|Rest]) :- right_of(R, L, Rest).

next_to(A, B, Street) :- right_of(A, B, Street).
next_to(A, B, Street) :- right_of(B, A, Street).

zebra(Owner, WaterDrinker, Street) :-
    length(Street, 5),
    member(house(englishman, red, _, _, _), Street),
    member(house(spaniard, _, _, _, dog), Street),
    member(house(_, green, coffee, _, _), Street),
    member(house(ukrainian, _, tea, _, _), Street),
    right_of(house(_, green, _, _, _), house(_, ivory, _, _, _), Street),
    member(house(_, _, _, oldgold, snails), Street),
    member(house(_, yellow, _, kools, _), Street),
    Street = [_, _, house(_, _, milk, _, _), _, _],
    Street = [house(norwegian, _, _, _, _)|_],
    next_to(house(_, _, _, chesterfields, _), house(_, _, _, _, fox), Street),
    next_to(house(_, yellow, _, kools, _), house(_, _, _, _, horse), Street),
    member(house(_, _, orangejuice, luckystrike, _), Street),
    member(house(japanese, _, _, parliaments, _), Street),
    next_to(house(norwegian, _, _, _, _), house(_, blue, _, _, _), Street),
    member(house(Owner, _, _, _, zebra), Street),
    member(house(WaterDrinker, _, water, _, _), Street).
