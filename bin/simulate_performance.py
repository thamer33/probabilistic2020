#!/usr/bin/env python
# fix problems with pythons terrible import system
import os
import sys
file_dir = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(file_dir, '../'))

# package imports
import permutation2020.python.utils as utils
from permutation2020.python.bootstrap import Bootstrap
from permutation2020.python.random_sample_names import RandomSampleNames
from permutation2020.python.random_tumor_types import RandomTumorTypes
import permutation2020.python.simulation_plots as plot_data
import permutation2020.python.simulation as sim
import permutation2020.python.mutation_context as mc

import permutation_test as pt
import probabilistic2020 as prob
import count_frameshifts as cf
import pandas as pd
import numpy as np
import pysam
import datetime
import argparse
import logging

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


def calc_performance(df, opts):
    """Function called by multiprocessing to run predictions.

    """
    # count frameshifts if needed
    if opts['kind'] != 'oncogene':
        fs_df = cf.count_frameshifts(df, opts['bed'], opts['bins'],
                                     opts['sample_number'], opts['use_unmapped'])
    else:
        fs_df=None
    # get statistical results
    permutation_df = prob.main(opts, mutation_df=df, frameshift_df=fs_df)

    # drop duplicates for counting average number of "driver" genes mutated
    df = df[df['is_nonsilent']==1]  # keep nonsilent mutations
    df = df.drop_duplicates(cols=['Tumor_Sample', 'Gene'])

    if opts['kind'] == 'oncogene':
        # count number of significant genes
        recur_sig_genes = permutation_df[permutation_df['recurrent BH q-value']<.1]['gene']
        ent_sig_genes = permutation_df[permutation_df['entropy BH q-value']<.1]['gene']
        recurrent_num_signif = len(recur_sig_genes)
        entropy_num_signif = len(ent_sig_genes)

        # count number of driver genes with non-silent mutations
        df_recur = df[df['Gene'].isin(recur_sig_genes)]
        df_ent = df[df['Gene'].isin(ent_sig_genes)]
        num_drivers_recur = df_recur.groupby('Tumor_Sample')['is_nonsilent'].sum()
        num_drivers_ent = df_ent.groupby('Tumor_Sample')['is_nonsilent'].sum()

        results = pd.DataFrame({'count': [recurrent_num_signif,
                                          entropy_num_signif],
                                'average num drivers': [np.mean(num_drivers_recur),
                                                        np.mean(num_drivers_ent)]},
                               index=['{0} recurrent'.format(opts['kind']),
                                      '{0} entropy'.format(opts['kind'])])
    elif opts['kind'] == 'tsg':
        # count number of significant genes
        deleterious_sig_genes = permutation_df[permutation_df['deleterious BH q-value']<.1]['gene']
        deleterious_num_signif = len(deleterious_sig_genes)

        # count number of driver genes with non-silent mutations
        df_del = df[df['Gene'].isin(deleterious_sig_genes)]
        num_drivers_del = df_del.groupby('Tumor_Sample')['is_nonsilent'].sum()

        results = pd.DataFrame({'count': [deleterious_num_signif],
                                'average num drivers': [np.mean(num_drivers_del)]},
                               index=['{0} deleterious'.format(opts['kind'])])
    elif opts['kind'] == 'effect':
        # count number of significant genes
        combined_sig_genes = permutation_df[permutation_df['combined BH q-value']<.1]['gene']
        effect_sig_genes = permutation_df[permutation_df['entropy-on-effect BH q-value']<.1]['gene']
        combined_num_signif = len(combined_sig_genes)
        effect_num_signif = len(effect_sig_genes)

        # count number of driver genes with non-silent mutations
        df_combined = df[df['Gene'].isin(combined_sig_genes)]
        df_eff = df[df['Gene'].isin(effect_sig_genes)]
        num_drivers_combined = df_combined.groupby('Tumor_Sample')['is_nonsilent'].sum()
        num_drivers_eff = df_eff.groupby('Tumor_Sample')['is_nonsilent'].sum()

        results = pd.DataFrame({'count': [effect_num_signif,
                                          combined_num_signif],
                                'average num drivers': [np.mean(num_drivers_combined),
                                                        np.mean(num_drivers_eff)]},
                               index=['entropy-on-effect',
                                      'combined'])

    return results


@utils.log_error_decorator
def singleprocess_simulate(info):
    dfg, opts = info  # unpack tuple
    df = next(dfg.dataframe_generator())
    single_result = calc_performance(df, opts)
    return single_result


def parse_arguments():
    # make a parser
    info = 'Examines the power of the statistical test as the amount of data increases.'
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
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-bs', '--bootstrap',
                       action='store_true',
                       default=False,
                       help='Perform bootstrap (sample with replacement) on mutations')
    group.add_argument('-rs', '--random-samples',
                       action='store_true',
                       default=False,
                       help='Perform sample with out replacement on samples/tumors')
    group.add_argument('-rt', '--random-tumor-type',
                       action='store_true',
                       default=False,
                       help='Perform sample with out replacement based on tumor types')
    parser.add_argument('-s', '--start-sample-rate',
                        type=float,
                        action='store',
                        default=0.1,
                        help='Lower end of sample rate interval for simulations. (Default: .1)')
    parser.add_argument('-e', '--end-sample-rate',
                        type=float,
                        action='store',
                        default=1.0,
                        help='Upper end of sample rate interval for simulations. (Default: 3.1)')
    parser.add_argument('-num', '--num-sample-rate',
                        type=int,
                        action='store',
                        default=7,
                        help='Number of sampling rates to simulate between '
                        'START_SAMPLE_RATE and END_SAMPLE_RATE. (Default: 7)')
    parser.add_argument('-iter', '--iterations',
                        type=int,
                        action='store',
                        default=10,
                        help='Number of iterations for each sample rate in the simulation')
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
    help_str = ('Background non-coding rate of INDELs with lengths matching '
                'frameshifts in --frameshift-counts option. Enter path to file '
                'generated by calc_non_coding_frameshift_rate.py.')
    parser.add_argument('-non-coding', '--non-coding-background',
                        type=str,
                        help=help_str)
    help_str = 'Number of bins to categorize framshift lengths by'
    parser.add_argument('-bins', '--bins',
                        type=int, default=5,
                        help=help_str)
    help_str = 'Number of sequenced samples'
    parser.add_argument('-sn', '--sample-number',
                        type=int, required=True,
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
    help_str = ('Kind of permutation test to perform ("oncogene" or "tsg"). "position-based" permutation '
                'test is intended to find oncogenes using position based statistics. '
                'The "deleterious" permutation test is intended to find tumor '
                'suppressor genes. (Default: oncogene)')
    parser.add_argument('-k', '--kind',
                        type=str, default='oncogene',
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
    help_str = ('Minimum number of mutations at a position for it to be '
                'considered a recurrently mutated position (Default: 3).')
    parser.add_argument('-r', '--recurrent',
                        type=int, default=3,
                        help=help_str)
    help_str = ('Fraction of total mutations in a gene. This define the '
                'minimumm number of mutations for a position to be defined '
                'as recurrently mutated (Defaul: .02).')
    parser.add_argument('-f', '--fraction',
                        type=float, default=.02,
                        help=help_str)
    help_str = ('Perform tsg permutation test if gene has '
                'at least a user specified number of deleterious mutations (default: 2)')
    parser.add_argument('-d', '--deleterious',
                        type=int, default=2,
                        help=help_str)
    help_str = ('Maximum TSG score to allow gene to be tested for oncogene '
                'permutation test. (Default: .10)')
    parser.add_argument('-t', '--tsg-score',
                        type=float, default=.10,
                        help=help_str)
    help_str = ('Deleterious mutation pseudo-count for null distribution '
                'statistics. (Default: 0)')
    parser.add_argument('-dp', '--deleterious-pseudo-count',
                        type=int, default=0,
                        help=help_str)
    help_str = ('Recurrent missense mutation pseudo-count for null distribution '
                'statistics. (Default: 0)')
    parser.add_argument('-rp', '--recurrent-pseudo-count',
                        type=int, default=0,
                        help=help_str)
    help_str = ('Specify the seed for the pseudo random number generator. '
                'By default, the seed is randomly chosen based. The seed will '
                'be used for the permutation test monte carlo simulations.')
    parser.add_argument('-seed', '--seed',
                        type=int, default=None,
                        help=help_str)
    help_str = 'Tab-delimited output path for performance simulation'
    parser.add_argument('-to', '--text-output',
                        type=str, required=True,
                        help=help_str)
    help_str = 'Plot output directory of performance simulation'
    parser.add_argument('-po', '--plot-output',
                        type=str, default='./',
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
    # hack for using probabilistic2020 main function
    opts.setdefault('output', '')

    # Get Mutations
    mut_df = pd.read_csv(opts['mutations'], sep='\t')

    # add column indicating non-silent mutations
    mut_df['is_nonsilent'] = mc.is_nonsilent(mut_df,
                                             utils.read_bed(opts['bed']),
                                             opts)

    # iterate through each sampling rate
    result = {}
    for sample_rate in np.linspace(opts['start_sample_rate'],
                                   opts['end_sample_rate'],
                                   opts['num_sample_rate']):
        if opts['bootstrap']:
            # bootstrap object for sub-sampling
            dfg = Bootstrap(mut_df.copy(),
                            subsample=sample_rate,
                            num_iter=opts['iterations'])
        elif opts['random_samples']:
            # sample with out replacement of sample names
            dfg = RandomSampleNames(mut_df.copy(),
                                    sub_sample=sample_rate,
                                    num_iter=opts['iterations'])
        else:
            # sample with out replacement of tumor types
            dfg = RandomTumorTypes(mut_df.copy(),
                                   sub_sample=sample_rate,
                                   num_iter=opts['iterations'])

        # perform simulation
        multiproces_output = sim.multiprocess_simulate(dfg, opts.copy(),
                                                       singleprocess_simulate)
        sim_results = {i: mydf for i, mydf in enumerate(multiproces_output)}

        # record result for a specific sample rate
        tmp_results = sim.calculate_stats(sim_results)
        result[sample_rate] = tmp_results

    # make pandas panel objects out of summarized
    # results from simulations
    panel_result = pd.Panel(result)

    sim.save_simulation_result(panel_result, opts['text_output'])

    # aggregate results for plotting
    plot_results = {'Permutation Test': panel_result}

    # plot number of predicted genes
    for plot_type in plot_results['Permutation Test'].major_axis:
        tmp_save_path = os.path.join(opts['plot_output'], plot_type + '.png')
        plot_data.count_errorbar(plot_results,
                                 gene_type=plot_type,
                                 save_path=tmp_save_path,
                                 title='Number of significant genes vs. relative size',
                                 xlabel='Sample rate',
                                 ylabel='Number of significant genes')
        tmp_save_path = os.path.join(opts['plot_output'], plot_type + '_avg_drivers.png')
        plot_data.count_errorbar(plot_results,
                                 gene_type=plot_type,
                                 save_path=tmp_save_path,
                                 title='Num predicted driver genes with non-silent mutations',
                                 xlabel='Sample rate',
                                 ylabel='Number of drivers per sample')


if __name__ == "__main__":
    opts = parse_arguments()
    main(opts)
