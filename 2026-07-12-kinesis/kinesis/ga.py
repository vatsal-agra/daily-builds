"""Genetic algorithm driving Kinesis evolution: tournament selection with
elitism, subtree crossover, and gaussian-perturbation + structural
mutation (both from genome.py), scored by simulate.run_simulation.
"""
import random
import json
import os

from .genome import Genome
from .simulate import run_simulation

TOURNAMENT_SIZE = 4
ELITE_FRACTION = 0.10
CROSSOVER_RATE = 0.7
PER_GENE_MUTATION_RATE = 0.25


class Individual:
    __slots__ = ("genome", "fitness", "distance", "energy", "toppled")

    def __init__(self, genome):
        self.genome = genome
        self.fitness = None
        self.distance = None
        self.energy = None
        self.toppled = None

    def evaluate(self, duration):
        result = run_simulation(self.genome, duration=duration)
        self.fitness = result.fitness
        self.distance = result.distance
        self.energy = result.energy
        self.toppled = result.toppled
        return result


class Population:
    def __init__(self, pop_size=60, seed=None, sim_duration=6.0):
        self.pop_size = pop_size
        self.sim_duration = sim_duration
        self.rng = random.Random(seed)
        self.individuals = [Individual(Genome.random(self.rng)) for _ in range(pop_size)]
        self.generation = 0
        self.history = []  # list of dict(generation, best, mean, worst)

    def evaluate_all(self):
        for ind in self.individuals:
            if ind.fitness is None:
                ind.evaluate(self.sim_duration)

    def _record_history(self):
        # Idempotent per generation number: step_generation() records the
        # *current* population before advancing, and run() also records
        # once more after its loop for the final generation reached. When
        # resuming from a checkpoint, the loaded population's generation
        # was already recorded before it was saved -- without this guard
        # the first step_generation() call after a resume would append a
        # second, duplicate entry for that same generation number.
        if self.history and self.history[-1]["generation"] == self.generation:
            return
        fits = [ind.fitness for ind in self.individuals]
        self.history.append({
            "generation": self.generation,
            "best": max(fits),
            "mean": sum(fits) / len(fits),
            "worst": min(fits),
        })

    def _tournament_select(self):
        contenders = self.rng.sample(self.individuals, TOURNAMENT_SIZE)
        return max(contenders, key=lambda ind: ind.fitness)

    def best(self):
        # step_generation() leaves non-elite members of the *new*
        # generation unevaluated (fitness=None) until the next
        # evaluate_all() call; evaluate defensively here so best() is
        # safe to call at any point, not just after run().
        self.evaluate_all()
        return max(self.individuals, key=lambda ind: ind.fitness)

    def step_generation(self):
        """Evaluate the current population (if not already), record
        history, then produce the next generation in place."""
        self.evaluate_all()
        self._record_history()

        ranked = sorted(self.individuals, key=lambda ind: ind.fitness, reverse=True)
        n_elite = max(1, int(ELITE_FRACTION * self.pop_size))
        next_gen = [Individual(ind.genome.clone()) for ind in ranked[:n_elite]]
        # carry elite fitness forward so they aren't re-simulated needlessly
        for new_ind, old_ind in zip(next_gen, ranked[:n_elite]):
            new_ind.fitness = old_ind.fitness
            new_ind.distance = old_ind.distance
            new_ind.energy = old_ind.energy
            new_ind.toppled = old_ind.toppled

        while len(next_gen) < self.pop_size:
            parent_a = self._tournament_select()
            if self.rng.random() < CROSSOVER_RATE:
                parent_b = self._tournament_select()
                child_genome = Genome.crossover(parent_a.genome, parent_b.genome, self.rng)
            else:
                child_genome = parent_a.genome.clone()
            child_genome = child_genome.mutate(self.rng, rate=PER_GENE_MUTATION_RATE)
            next_gen.append(Individual(child_genome))

        self.individuals = next_gen
        self.generation += 1

    def run(self, generations, log=None):
        for _ in range(generations):
            self.step_generation()
            if log is not None:
                h = self.history[-1]
                log(h)
        self.evaluate_all()
        self._record_history()
        return self.history

    # ---- persistence ----

    def to_dict(self):
        return {
            "pop_size": self.pop_size,
            "sim_duration": self.sim_duration,
            "generation": self.generation,
            "history": self.history,
            "individuals": [
                {"genome": ind.genome.to_dict(), "fitness": ind.fitness,
                 "distance": ind.distance, "energy": ind.energy, "toppled": ind.toppled}
                for ind in self.individuals
            ],
        }

    def save(self, path):
        # Guarantee every serialized individual has a real fitness (never
        # a null from an unevaluated fresh population) so anything reading
        # the checkpoint back -- gallery/replay/fitness-chart, or a future
        # resumed run -- can rely on it without a defensive null-check.
        self.evaluate_all()
        # An evolve run can take many minutes; failing to write the result
        # because the output directory doesn't exist yet would throw the
        # whole run away, so create it rather than erroring.
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f)

    @staticmethod
    def from_dict(d, seed=None):
        pop = Population.__new__(Population)
        pop.pop_size = d["pop_size"]
        pop.sim_duration = d["sim_duration"]
        pop.rng = random.Random(seed)
        pop.generation = d["generation"]
        pop.history = d["history"]
        pop.individuals = []
        for item in d["individuals"]:
            ind = Individual(Genome.from_dict(item["genome"]))
            ind.fitness = item["fitness"]
            ind.distance = item["distance"]
            ind.energy = item["energy"]
            ind.toppled = item["toppled"]
            pop.individuals.append(ind)
        return pop

    @staticmethod
    def load(path, seed=None):
        with open(path) as f:
            d = json.load(f)
        return Population.from_dict(d, seed=seed)
