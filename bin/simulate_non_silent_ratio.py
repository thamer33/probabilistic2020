#!/usr/bin/env python
# fix problems with pythons terrible import system
import sys
import os
file_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(file_dir, '../'))

# package import
import permutation2020.python.permutation as pm
import permutation2020.python.utils as utils
from permutation2020.python.gene_sequence import GeneSequence
import permutation2020.cython.cutils as cutils
import permutation2020.python.mutation_context as mc

# external imports
import numpy as np
import pandas as pd
import pysam
from multiprocessing import Pool
import argparse
import datetime
import logging
import copy

logger = logging.getLogger(__name__)  # module logger

def start_logging(log_file='', log_level='INFO'):
    """Start logging information into the log directory.

    If os.devnull is specified as the log_file then the log file will
    not actually be written to a file.
    """
    if not log_file:
        # create log directory if it doesn't exist
        log_dir = os.path.abspath('log') + '/'
        if not os.path.isdir(log_dir):
            os.mkdir(log_dir)

        # path to new log file
        log_file = log_dir + 'log.run.' + str(datetime.datetime.now()).replace(':', '.') + '.txt'

    # logger options
    lvl = logging.DEBUG if log_level.upper() == 'DEBUG' else logging.INFO
    myformat = '%(asctime)s - %(name)s - %(levelname)s \n>>>  %(message)s'

    # create logger
    if not log_file == 'stdout':
        # normal logging to a regular file
        logging.basicConfig(level=lvl,
                            format=myformat,
                            filename=log_file,
                            filemode='w')
    else:
        # logging to stdout
        root = logging.getLogger()
        root.setLevel(lvl)
        stdout_stream = logging.StreamHandler(sys.stdout)
        stdout_stream.setLevel(lvl)
        formatter = logging.Formatter(myformat)
        stdout_stream.setFormatter(formatter)
        root.addHandler(stdout_stream)
        root.propagate = True


def multiprocess_permutation(bed_dict, mut_df, opts):
    """Handles parallelization of permutations by splitting work
    by chromosome.
    """
    chroms = sorted(bed_dict.keys())
    multiprocess_flag = opts['processes']>0
    if multiprocess_flag:
        num_processes = opts['processes']
    else:
        num_processes = 1
    num_permutations = opts['num_permutations']
    obs_result = []
    result_list = [[0, 0, 0, 0, 0, 0, 0] for k in range(num_permutations)]
    for i in range(0, len(chroms), num_processes):
        if multiprocess_flag:
            pool = Pool(processes=num_processes)
            tmp_num_proc = len(chroms) - i if i + num_processes > len(chroms) else num_processes
            info_repeat = ((bed_dict[chroms[tmp_ix]], mut_df, opts)
                            for tmp_ix in range(i, i+tmp_num_proc))
            process_results = pool.imap(singleprocess_permutation, info_repeat)
            process_results.next = utils.keyboard_exit_wrapper(process_results.next)
            try:
                for chrom_result, obs_mutations in process_results:
                    for j in range(num_permutations):
                        result_list[j][0] += chrom_result[j][0]
                        result_list[j][1] += chrom_result[j][1]
                        result_list[j][2] += chrom_result[j][2]
                        result_list[j][3] += chrom_result[j][3]
                        result_list[j][4] += chrom_result[j][4]
                        result_list[j][5] += chrom_result[j][5]
                        result_list[j][6] += chrom_result[j][6]
                    obs_result.append(obs_mutations)
            except KeyboardInterrupt:
                pool.close()
                pool.join()
                logger.info('Exited by user. ctrl-c')
                sys.exit(0)
            pool.close()
            pool.join()
        else:
            info = (bed_dict[chroms[i]], mut_df, opts)
            chrom_result, obs_mutations = singleprocess_permutation(info)
            for j in range(num_permutations):
                result_list[j][0] += chrom_result[j][0]
                result_list[j][1] += chrom_result[j][1]
                result_list[j][2] += chrom_result[j][2]
                result_list[j][3] += chrom_result[j][3]
                result_list[j][4] += chrom_result[j][4]
                result_list[j][5] += chrom_result[j][5]
                result_list[j][6] += chrom_result[j][6]
            obs_result.append(obs_mutations)

    return result_list, obs_result


def multiprocess_gene_shuffle(info, opts):
    """Handles parallelization of permutations by splitting work
    by chromosome.
    """
    chroms = sorted(info.keys())
    multiprocess_flag = opts['processes']>0
    if multiprocess_flag:
        num_processes = opts['processes']
    else:
        num_processes = 1
    num_permutations = opts['num_permutations']
    result_list = [[0, 0] for k in range(num_permutations)]
    for i in range(0, len(chroms), num_processes):
        if multiprocess_flag:
            pool = Pool(processes=num_processes)
            tmp_num_proc = len(chroms) - i if i + num_processes > len(chroms) else num_processes
            info_repeat = (info[chroms[tmp_ix]] + [num_permutations]
                           for tmp_ix in range(i, i+tmp_num_proc))
            process_results = pool.imap(singleprocess_gene_shuffle, info_repeat)
            process_results.next = utils.keyboard_exit_wrapper(process_results.next)
            try:
                for chrom_result in process_results:
                    for j in range(num_permutations):
                        result_list[j][0] += chrom_result[j][0]
                        result_list[j][1] += chrom_result[j][1]
            except KeyboardInterrupt:
                pool.close()
                pool.join()
                logger.info('Exited by user. ctrl-c')
                sys.exit(0)
            pool.close()
            pool.join()
        else:
            info_repeat = info[chroms[i]] + [num_permutations]
            chrom_result = singleprocess_gene_shuffle(info_repeat)
            for j in range(num_permutations):
                result_list[j][0] += chrom_result[j][0]
                result_list[j][1] += chrom_result[j][1]

    return result_list


@utils.log_error_decorator
def singleprocess_gene_shuffle(info):
    #num_permutations = info[0][-1]  # number of permutations is always last column
    num_permutations = info.pop(-1)  # number of permutations is always last column
    result = [[0, 0] for k in range(num_permutations)]
    for (context_cts, context_to_mutations, mut_df, gs, sc) in info:
        ## Do permutations
        # calculate non silent count
        tmp_result = pm.non_silent_ratio_permutation(context_cts,
                                                     context_to_mutations,
                                                     sc,  # sequence context obj
                                                     gs,  # gene sequence obj
                                                     num_permutations)

        # increment the non-silent/silent counts for each permutation
        for j in range(num_permutations):
            result[j][0] += tmp_result[j][0]
            result[j][1] += tmp_result[j][1]
    return result


@utils.log_error_decorator
def singleprocess_permutation(info):
    bed_list, mut_df, opts = info
    current_chrom = bed_list[0].chrom
    logger.info('Working on chromosome: {0} . . .'.format(current_chrom))
    num_permutations = opts['num_permutations']
    gene_fa = pysam.Fastafile(opts['input'])
    gs = GeneSequence(gene_fa, nuc_context=opts['context'])

    # variables for recording the actual observed number of non-silent
    # vs. silent mutations
    obs_silent = 0
    obs_non_silent = 0
    obs_nonsense = 0
    obs_loststop = 0
    obs_splice_site = 0
    obs_loststart = 0
    obs_missense = 0

    # go through each gene to permform simulation
    result = [[0, 0, 0, 0, 0, 0, 0] for k in range(num_permutations)]
    for bed in bed_list:
        # compute context counts and somatic bases for each context
        gene_tuple = mc.compute_mutation_context(bed, gs, mut_df, opts)
        context_cts, context_to_mutations, mutations_df, gs, sc = gene_tuple

        if context_to_mutations:
            ## get information about observed non-silent counts
            # get info about mutations
            tmp_mut_info = mc.get_aa_mut_info(mutations_df['Coding Position'],
                                              mutations_df['Tumor_Allele'].tolist(),
                                              gs)
            # calc deleterious mutation info
            tmp_non_silent = cutils.calc_non_silent_info(tmp_mut_info['Reference AA'],
                                                         tmp_mut_info['Somatic AA'],
                                                         tmp_mut_info['Codon Pos'])
            obs_non_silent += tmp_non_silent[0]
            obs_silent += tmp_non_silent[1]
            obs_nonsense += tmp_non_silent[2]
            obs_loststop += tmp_non_silent[3]
            obs_splice_site += tmp_non_silent[4]
            obs_loststart += tmp_non_silent[5]
            obs_missense += tmp_non_silent[6]

            ## Do permutations
            # calculate non silent count
            tmp_result = pm.non_silent_ratio_permutation(context_cts,
                                                         context_to_mutations,
                                                         sc,  # sequence context obj
                                                         gs,  # gene sequence obj
                                                         num_permutations)
        else:
            tmp_result = [[0, 0, 0, 0, 0, 0, 0] for k in range(num_permutations)]

        # increment the non-silent/silent counts for each permutation
        for j in range(num_permutations):
            result[j][0] += tmp_result[j][0]
            result[j][1] += tmp_result[j][1]
            result[j][2] += tmp_result[j][2]
            result[j][3] += tmp_result[j][3]
            result[j][4] += tmp_result[j][4]
            result[j][5] += tmp_result[j][5]
            result[j][6] += tmp_result[j][6]

    gene_fa.close()
    obs_result = [obs_non_silent, obs_silent, obs_nonsense,
                  obs_loststop, obs_splice_site, obs_loststart, obs_missense]
    logger.info('Finished working on chromosome: {0}.'.format(current_chrom))
    return result, obs_result


def parse_arguments():
    # make a parser
    info = 'Simulates the non-silent mutation ratio by randomly permuting mutations'
    parser = argparse.ArgumentParser(description=info)

    # logging arguments
    parser.add_argument('-ll', '--log-level',
                        type=str,
                        action='store',
                        default='',
                        help='Write a log file (--log-level=DEBUG for debug mode, '
                        '--log-level=INFO for info mode)')
    parser.add_argument('-l', '--log',
                        type=str,
                        action='store',
                        default='',
                        help='Path to log file. (accepts "stdout")')

    # program arguments
    help_str = 'gene FASTA file from extract_gene_seq.py script'
    parser.add_argument('-i', '--input',
                        type=str, required=True,
                        help=help_str)
    help_str = 'DNA mutations file'
    parser.add_argument('-m', '--mutations',
                        type=str, required=True,
                        help=help_str)
    help_str = 'BED file annotation of genes'
    parser.add_argument('-b', '--bed',
                        type=str, required=True,
                        help=help_str)
    help_str = ('Number of processes to use. 0 indicates using a single '
                'process without using a multiprocessing pool '
                '(more means Faster, default: 0).')
    parser.add_argument('-p', '--processes',
                        type=int, default=0,
                        help=help_str)
    help_str = ('Number of permutations for null model. p-value precision '
                'increases with more permutations (Default: 10000).')
    parser.add_argument('-n', '--num-permutations',
                        type=int, default=10000,
                        help=help_str)
    help_str = ('Number of DNA bases to use as context. 0 indicates no context. '
                '1 indicates only use the mutated base.  1.5 indicates using '
                'the base context used in CHASM '
                '(http://wiki.chasmsoftware.org/index.php/CHASM_Overview). '
                '2 indicates using the mutated base and the upstream base. '
                '3 indicates using the mutated base and both the upstream '
                'and downstream bases. (Default: 1.5)')
    parser.add_argument('-c', '--context',
                        type=float, default=1.5,
                        help=help_str)
    help_str = ('Shuffle gene names randomly in mutation permutation. Shuffling reassigns all '
               'mutations from a gene "X" to a new gene "Y". The mutations in '
               '"Y" are also shuffled to a new gene. Mutational context counts '
               'are evaluated on the actual gene and these counts are then used '
               'to perform the permutation on the new gene.')
    parser.add_argument('-s', '--shuffle-genes',
                        action='store_true',
                        help=help_str)
    help_str = ('Use mutations that are not mapped to the the single reference '
                'transcript for a gene specified in the bed file indicated by '
                'the -b option.')
    parser.add_argument('-u', '--use-unmapped',
                        action='store_true',
                        default=False,
                        help=help_str)
    help_str = ('Path to the genome fasta file. Required if --use-unmapped flag '
                'is used. (Default: None)')
    parser.add_argument('-g', '--genome',
                        type=str, default='',
                        help=help_str)
    help_str = 'Output text file of results'
    parser.add_argument('-o', '--output',
                        type=str, required=True,
                        help=help_str)
    args = parser.parse_args()

    # handle logging
    if args.log_level or args.log:
        if args.log:
            log_file = args.log
        else:
            log_file = ''  # auto-name the log file
    else:
        log_file = os.devnull
    log_level = args.log_level
    start_logging(log_file=log_file,
                  log_level=log_level)  # start logging

    opts = vars(args)
    if opts['use_unmapped'] and not opts['genome']:
        print('You must specify a genome fasta with -g if you set the '
              '--use-unmapped flag to true.')
        sys.exit(1)

    # log user entered command
    logger.info('Command: {0}'.format(' '.join(sys.argv)))
    return opts


def main(opts):
    # hack to index the FASTA file
    gene_fa = pysam.Fastafile(opts['input'])
    gene_fa.close()

    # Get Mutations
    mut_df = pd.read_csv(opts['mutations'], sep='\t')
    orig_num_mut = len(mut_df)
    mut_df = mut_df.dropna(subset=['Tumor_Allele', 'Start_Position', 'Chromosome'])
    logger.info('Kept {0} mutations after droping mutations with missing '
                'information (Droped: {1})'.format(len(mut_df), orig_num_mut - len(mut_df)))

    # select valid single nucleotide variants only
    mut_df = utils._fix_mutation_df(mut_df)

    # read in bed info
    bed_dict = utils.read_bed(opts['bed'], [])

    # if user designated to shuffle gene names, then precompute mutation context
    # info so that they can be reassigned to a new gene
    if opts['shuffle_genes']:
        # compute mutation context counts for all genes
        gene_fa = pysam.Fastafile(opts['input'])
        gs = GeneSequence(gene_fa, nuc_context=opts['context'])
        logger.info('Computing gene context counts . . .')
        for chrom in bed_dict:
            bed_dict[chrom] = [list(mc.compute_mutation_context(b, gs, mut_df, opts))
                               for b in bed_dict[chrom]]
        logger.info('Computed all mutational context counts.')

        # filter out genes that have no mutations
        for chrom in bed_dict:
            bed_dict[chrom] = filter(lambda x: x[1], bed_dict[chrom])

        # shuffle gene mutation context counts
        logger.info('Shuffling gene names . . .')
        #gene_pos = [[chrom, i]
                    #for chrom in bed_dict
                    #for gene_list in bed_dict[chrom]
                    #for i, gene_info in enumerate(gene_list)]
        gene_pos = [[chrom, i]
                    for chrom, gene_list in bed_dict.iteritems()
                    for i in range(len(gene_list))]
        shuffled_gene_pos = copy.deepcopy(gene_pos)
        prng = np.random.RandomState()
        prng.shuffle(shuffled_gene_pos)  # shuffling happens inplace

        # update info with new shuffled gene name
        old_bed_dict = {chrom: [gene_row[:2] for gene_row in bed_dict[chrom]]
                        for chrom in bed_dict}
        #old_bed_dict = copy.deepcopy(bed_dict)
        for i in range(len(shuffled_gene_pos)):
            old_chrom, old_pos = gene_pos[i]
            new_chrom, new_pos = shuffled_gene_pos[i]
            tmp_context_cts = old_bed_dict[old_chrom][old_pos][0]
            tmp_context2mut = old_bed_dict[old_chrom][old_pos][1]
            bed_dict[new_chrom][new_pos][0] = tmp_context_cts
            bed_dict[new_chrom][new_pos][1] = tmp_context2mut
        logger.info('Finished shuffling gene names.')

        #permutation_result = multiprocess_gene_shuffle(bed_dict, opts)
        sim_result = multiprocess_gene_shuffle(bed_dict, opts)
    # if user doesn't shuffle genes, then it is a regular evalutation
    # of non-silent/silent ratio based on the genes the mutations actually
    # occurred in
    else:
        # perform permutation test
        #permutation_result = multiprocess_permutation(bed_dict, mut_df, opts)
        sim_result, obs_result = multiprocess_permutation(bed_dict, mut_df, opts)

        # report number of observed non-silent and silent mutations
        #obs_result = [x[1] for x in permutation_result]  # actually observed num mutations
        #obs_result = permutation_result[1]  # actually observed num mutations
        total_non_silent = sum(o[0] for o in obs_result)
        total_silent = sum(o[1] for o in obs_result)
        total_nonsense = sum(o[2] for o in obs_result)
        total_loststop = sum(o[3] for o in obs_result)
        total_splice_site = sum(o[4] for o in obs_result)
        total_loststart = sum(o[5] for o in obs_result)
        total_missense = sum(o[6] for o in obs_result)
        logger.info('There were {0} non-silent SNVs and {1} silent SNVs actually '
                    'observed from the provided mutations.'.format(total_non_silent,
                                                                   total_silent))
        logger.info('There were {0} missense SNVs, {1} nonsense SNVs, {2} lost stop SNVs, '
                    ', {3} lost start, and {4} splice site SNVs'.format(total_missense,
                                                      total_nonsense,
                                                      total_loststop,
                                                      total_loststart,
                                                      total_splice_site))

    #sim_result = [s[0] for s in permutation_result]  # results with permutation
    #sim_result = permutation_result[0]

    # convert to dataframe to save to file
    cols = ['non-silent count', 'silent count', 'nonsense count',
            'lost stop count', 'splice site count', 'lost start count',
            'missense count']
    non_silent_ratio_df = pd.DataFrame(sim_result,
                                       columns=cols)
    # save output
    non_silent_ratio_df.to_csv(opts['output'], sep='\t', index=False)

    return non_silent_ratio_df


if __name__ == "__main__":
    opts = parse_arguments()
    main(opts)
