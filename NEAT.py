from generation_statistics import GenerationStatistics
import time
import numpy as np
from genome_neural_network import GenomeNeuralNetwork
from reproduce import Reproduce
from species import SpeciesSet

# Exception used to check if there are no more species
from stagnation import Stagnation


class CompleteExtinctionException(Exception):
    pass


class NEAT:

    def __init__(self, x_training_data, y_training_data, config, fitness_threshold):
        # Where all the parameters are saved
        self.config = config
        # Takes care of reproduction of populations
        self.reproduction = Reproduce(stagnation=Stagnation, config=config)
        self.generation_tracker = GenerationStatistics()
        # Track the best genome across generations
        self.best_all_time_genome = None
        # If the fitness threshold is met it will stop the algorithm (if set)
        self.fitness_threshold = fitness_threshold
        # A class containing the different species within the population
        self.species_set = SpeciesSet(config=config, generation_tracker=self.generation_tracker)
        self.x_train = x_training_data
        self.y_train = y_training_data

        # Initialise the starting population
        self.population = self.reproduction.create_new_population(population_size=self.config.population_size,
                                                                  num_features=x_training_data.shape[1])

        # Speciate the initial population
        self.species_set.speciate(population=self.population, compatibility_threshold=3, generation=0)

    def evaluate_population(self, use_backprop, generation):
        """
        Calculates the fitness value for each individual genome in the population
        :type use_backprop: True or false on whether you're calculating the fitness using backprop or not
        :param generation: Which generation number it currently is
        :return: The best genome of the population
        """

        # Should return the best genome
        current_best_genome = None

        for genome in self.population.values():

            genome_nn = GenomeNeuralNetwork(genome=genome, x_train=self.x_train, y_train=self.y_train,
                                            create_weights_bias_from_genome=True, activation_type='sigmoid',
                                            learning_rate=0.1, num_epochs=1000, batch_size=64)

            # Optimise the neural_network_first. However, the generation should allow for one pass so that we are not
            #  just optimising all the same topologies
            if use_backprop and generation > 1:
                print('\n')
                print('OPTIMISING GENOME')
                # NOTE: Genome fitness can be none due to crossover because fitness value not carried over
                print('Genome Fitness Before: {}'.format(genome.fitness))
                genome_nn.optimise(print_epoch=False)

            # We use genome_nn.x_train instead of self.x_train because the genome_nn might have deleted a row if there
            # is no connection to one of the sources
            cost = genome_nn.run_one_pass(input_data=genome_nn.x_train, labels=self.y_train, return_cost_only=True)

            # The fitness is the negative of the cost. Because less cost = greater fitness
            genome.fitness = -cost

            # Only print genome fitness after is back prop is used since back prop takes a long time so this can be a
            #  way of tracking progress in the meantime
            if use_backprop and generation > 1:
                print('Genome Fitness After: {}'.format(genome.fitness))

            if current_best_genome is None or genome.fitness > current_best_genome.fitness:
                current_best_genome = genome

        return current_best_genome

    def update_population_toplogy_info(self):
        num_nodes_overall = []
        num_nodes_enabled = []
        num_connections_overall = []
        num_connections_enabled = []
        all_fitnesses = []
        for genome in self.population.values():
            num_nodes_overall.append(len(genome.nodes))
            num_nodes_enabled.append(len(genome.get_active_nodes()))
            num_connections_overall.append(len(genome.connections))
            num_connections_enabled.append(genome.check_connection_enabled_amount())
            if genome.fitness:
                all_fitnesses.append(genome.fitness)

        self.generation_tracker.mean_number_connections_enabled = np.mean(num_connections_enabled)
        self.generation_tracker.mean_number_connections_overall = np.mean(num_connections_overall)

        self.generation_tracker.mean_number_nodes_enabled = np.mean(num_nodes_enabled)
        self.generation_tracker.mean_number_nodes_overall = np.mean(num_nodes_overall)

        self.generation_tracker.average_population_fitness = np.mean(all_fitnesses)

    def run(self, max_num_generations, use_backprop, print_generation_information):
        """
        Run the algorithm
        """

        current_gen = 0
        while current_gen < max_num_generations:
            # Every generation increment
            current_gen += 1

            self.generation_tracker.population_size = len(self.population)

            start_evaluate_time = time.time()
            # Evaluate the current generation and get the best genome in the current generation
            best_current_genome = self.evaluate_population(use_backprop=use_backprop, generation=current_gen)
            end_evaluate_time = time.time()
            self.generation_tracker.evaluate_execute_time = end_evaluate_time - start_evaluate_time

            # Keep track of the best genome across generations
            if self.best_all_time_genome is None or best_current_genome.fitness > self.best_all_time_genome.fitness:
                self.best_all_time_genome = best_current_genome

            self.generation_tracker.best_all_time_genome_fitness = self.best_all_time_genome.fitness

            # If the fitness threshold is met, stop the algorithm
            if self.best_all_time_genome.fitness > self.fitness_threshold:
                break

            start_reproduce_time = time.time()

            # Reset attributes for the current generation
            self.generation_tracker.reset_tracker_attributes()

            # Reproduce and get the next generation
            self.population = self.reproduction.reproduce(species_set=self.species_set,
                                                          population_size=self.config.population_size,
                                                          generation=current_gen,
                                                          generation_tracker=self.generation_tracker,
                                                          # current_gen should be greater than one ot use
                                                          # backprop_mutation because we let the first generation
                                                          # mutate just as if it was the normal genetic algorithm,
                                                          # so that we're not optimising all of the same structure
                                                          backprop_mutation=(use_backprop and current_gen > 1))
            end_reproduce_time = time.time()
            self.generation_tracker.reproduce_execute_time = end_reproduce_time - start_reproduce_time

            # TODO: Uncomment this if it causes an issue
            # # Allow for some leaway in population size (+- 5)
            # range_value = 5
            # range_of_population_sizes = set(range(self.config.population_size - range_value,
            #                                       self.config.population_size + range_value + 1))
            # if len(self.population) not in range_of_population_sizes:
            #     raise Exception('There is an incorrect number of genomes in the population')

            # Check to ensure no genes share the same connection gene addresses. (This problem has been fixed but is
            # here just incase now).
            self.ensure_no_duplicate_genes()

            # Check if there are any species, if not raise an exception. TODO: Let user reset population if extinction
            if not self.species_set.species:
                raise CompleteExtinctionException()

            start_specify_time = time.time()
            # Speciate the current generation
            self.species_set.speciate(population=self.population, generation=current_gen,
                                      compatibility_threshold=self.config.compatibility_threshold,
                                      generation_tracker=self.generation_tracker)
            end_specify_time = time.time()
            self.generation_tracker.species_execute_time = end_specify_time - start_specify_time

            self.update_population_toplogy_info()

            self.generation_tracker.update_generation_information(generation=current_gen)
            if print_generation_information:
                self.generation_tracker.print_generation_information(generation_interval_for_graph=150)

            # Gives distribution of the weights in the population connections
            self.reproduction.show_population_weight_distribution(population=self.population)

        return self.best_all_time_genome

    def ensure_no_duplicate_genes(self):
        connection_gene_dict = {}
        for genome in self.population.values():
            for connection in genome.connections.values():
                if connection not in connection_gene_dict:
                    connection_gene_dict[connection] = 1
                else:
                    connection_gene_dict[connection] += 1

        for connection_gene, amount in connection_gene_dict.items():
            if amount > 1:
                raise Exception('You have duplicated a connection gene')
