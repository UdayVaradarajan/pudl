"""A module with functions to aid in data analysis using the PUDL database."""

# Useful high-level external modules.
import numpy as np
import pandas as pd
import sqlalchemy as sa
import matplotlib.pyplot as plt
import itertools
import random

# Our own code...
from pudl import pudl, ferc1, eia923, settings, constants
from pudl import models, models_ferc1, models_eia923
from pudl import clean_eia923, clean_ferc1, clean_pudl
from pudl import outputs


def merge_on_date_year(df_date, df_year, on=[], how='inner',
                       date_col='report_date',
                       year_col='report_date'):
    """
    Merge two dataframes based on a shared year.

    Some of our data is annual, and has an integer year column (e.g. FERC 1).
    Some of our data is annual, and uses a Date column (e.g. EIA 860), and
    some of our data has other temporal resolutions, and uses date columns
    (e.g. EIA 923 fuel receipts are monthly, EPA CEMS data is hourly). This
    function takes two data frames and merges them based on the year that the
    data pertains to.  It requires one of the dataframes to have annual
    resolution, and allows the annual time to be described as either an integer
    year or a Date. The non-annual dataframe must have a Date column.

    By default, it is assumed that both the date and annual columns to be
    merged on are called 'report_date' since that's the common case when
    bringing together EIA860 and EIA923 data.

    Args:
        df_date: the dataframe with a more granular date column, the label of
            which is specified by date_col (report_date by default)
        df_year: the dataframe with a column containing annual dates, the label
            of which is specified by year_col (report_date by default)
        on: The list of columns to merge on, other than the year and date
            columns.
        date_col: name of the date column to use to find the year to merge on.
            Must be a Date.
        year_col: name of the year column to merge on. Must be a Date
            column with annual resolution.

    Returns:
        merged: a dataframe with a date column, but no year columns, and only
            one copy of any shared columns that were not part of the list of
            columns to be merged on.  The values from df1 are the ones which
            are retained for any shared, non-merging columns.
    """
    assert date_col in df_date.columns.tolist()
    assert year_col in df_year.columns.tolist()
    assert pd.infer_freq(
        pd.DatetimeIndex(df_year[year_col].unique()).sort_values()) == 'AS-JAN'
    # assert that df_date has annual or finer time resolution.

    # Create a temporary column in each dataframe with the year
    df_year['year_temp'] = pd.to_datetime(df_year[year_col]).dt.year
    # Drop the yearly report_date column: this way there won't be duplicates
    # and the final df will have the more granular report_date.
    df_year = df_year.drop([year_col], axis=1)
    df_date['year_temp'] = pd.to_datetime(df_date[date_col]).dt.year

    full_on = on + ['year_temp']
    unshared_cols = [col for col in df_year.columns.tolist()
                     if col not in df_date.columns.tolist()]
    cols_to_use = unshared_cols + full_on

    # Merge and drop the temp
    merged = pd.merge(df_date, df_year[cols_to_use], how=how, on=full_on)
    merged = merged.drop(['year_temp'], axis=1)

    return(merged)


def simple_select(table_name, pudl_engine):
    """
    Simple select statement.

    Args:
        table_name: pudl table name
        pudl_engine

    Returns:
        DataFrame from table
    """
    # Pull in the table
    tbl = models.PUDLBase.metadata.tables[table_name]
    # Creates a sql Select object
    select = sa.sql.select([tbl, ])
    # Converts sql object to pandas dataframe

    table = pd.read_sql(select, pudl_engine)

    # If table includes plant_id, get the PUDL Plant ID

    if 'plant_id' in table.columns:
        # Shorthand for readability... pt = PUDL Tables
        pt = models.PUDLBase.metadata.tables

        # Pull in plants_eia which connects EIA & PUDL plant IDs
        plants_eia_tbl = pt['plants_eia']
        plants_eia_select = sa.sql.select([
            plants_eia_tbl.c.plant_id,
            plants_eia_tbl.c.plant_id_pudl,
        ])
        plants_eia = pd.read_sql(plants_eia_select, pudl_engine)
        out_df = pd.merge(table, plants_eia, how='left', on='plant_id')
        out_df.rename(columns={'plant_id': 'plant_id_eia'}, inplace=True)
        out_df.plant_id_pudl = out_df.plant_id_pudl.astype(int)
        table = out_df
    else:
        table = table

    return(table)


def simple_ferc1_plant_ids(pudl_engine):
    """Generate list of all PUDL plant IDs which map to a single FERC plant."""
    ferc1_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_ferc''',
                                  pudl_engine)
    ferc1_simple_plant_ids = ferc1_plant_ids.drop_duplicates('plant_id_pudl',
                                                             keep=False)
    return(ferc1_simple_plant_ids)


def simple_eia_plant_ids(pudl_engine):
    """Generate list of all PUDL plant IDs which map to a single EIA plant."""
    eia_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_eia''',
                                pudl_engine)
    eia_simple_plant_ids = eia_plant_ids.drop_duplicates('plant_id_pudl',
                                                         keep=False)
    return(eia_simple_plant_ids)


def simple_pudl_plant_ids(pudl_engine):
    """Get all PUDL plant IDs that map to single EIA & single FERC plant ID."""
    ferc1_simple = simple_ferc1_plant_ids(pudl_engine)
    eia_simple = simple_eia_plant_ids(pudl_engine)
    pudl_simple = np.intersect1d(ferc1_simple['plant_id_pudl'],
                                 eia_simple['plant_id_pudl'])
    return(pudl_simple)


def ferc_eia_shared_plant_ids(pudl_engine):
    """Generate a list of PUDL plant IDs that appear in both FERC and EIA."""
    ferc_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_ferc''',
                                 pudl_engine)
    eia_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_eia''',
                                pudl_engine)
    shared_plant_ids = np.intersect1d(ferc_plant_ids['plant_id_pudl'],
                                      eia_plant_ids['plant_id_pudl'])
    return(shared_plant_ids)


def ferc_pudl_plant_ids(pudl_engine):
    """Generate a list of PUDL plant IDs that correspond to FERC plants."""
    ferc_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_ferc''',
                                 pudl_engine)
    return(ferc_plant_ids)


def eia_pudl_plant_ids(pudl_engine):
    """Generate a list of PUDL plant IDs that correspond to EIA plants."""
    eia_plant_ids = pd.read_sql('''SELECT plant_id_pudl FROM plants_eia''',
                                pudl_engine)
    return(eia_plant_ids)


def yearly_sum_eia(df, sum_by, columns=['plant_id_eia', 'generator_id']):
    """
    Group an input dataframe by serveral columns, and calculate annual sums.

    The dataframe to group and sum is 'table'. The column to sum on an annual
    basis is 'sum_by' and 'columns' is the set of fields to group the dataframe
    by before summing.

    The dataframe can start with either a report_year or report_date field. If
    it's got a report_date, that's converted into an integer year field named
    report_year.

    Comments from Zane:
     - If we implement consistent report_year and report_date naming
       convention in our database tables, then I think we could eliminate
       the need to pass in a date/year column? If there's a report_date
       then we'd turn it into a report_year, and if there's a report_year, then
       it's ready to go.
     - Might want to do some assert() checking to make sure we have a valid
       date or year field in the dataframe that's passed in.
     - Does this need to be an EIA specific function? If we're using the same
       report_year and report_date convention in other data sources could we
       make it work for them as well?
     - Why did we end up converting things to integer years rather than using
       the native time-based grouping functions?
    """
    df['report_year'] = pd.to_datetime(df['report_date']).dt.year
    gb = df.groupby(by=columns)
    return(gb.agg({sum_by: np.sum}))


def capacity_factor(g9_summed, g8, id_col='plant_id_eia'):
    """Generate capacity facotrs for all EIA generators."""
    # merge the generation and capacity to calculate capacity fazctor
    # plant_id should be specified as either plant_id_eia or plant_id_pudl
    capacity_factor = g9_summed.merge(g8,
                                      on=['plant_id_eia', 'plant_id_pudl',
                                          'generator_id',
                                          'report_year'])
    capacity_factor['capacity_factor'] = \
        capacity_factor['net_generation_mwh'] / \
        (capacity_factor['nameplate_capacity_mw'] * 8760)

    # Replace unrealistic capacity factors with NaN: < 0 or > 1.5
    capacity_factor.loc[capacity_factor['capacity_factor']
                        < 0, 'capacity_factor'] = np.nan
    capacity_factor.loc[capacity_factor['capacity_factor']
                        >= 1.5, 'capacity_factor'] = np.nan

    if 'plant_id_pudl_x' in capacity_factor.columns:
        capacity_factor.rename(
            columns={'plant_id_pudl_x': 'plant_id_pudl'}, inplace=True)
    if 'plant_id_pudl_y' in capacity_factor.columns:
        capacity_factor.drop('plant_id_pudl_y', axis=1, inplace=True)
    if 'plant_id_eia_x' in capacity_factor.columns:
        capacity_factor.rename(
            columns={'plant_id_eia_x': 'plant_id_eia'}, inplace=True)
    if 'plant_id_eia_y' in capacity_factor.columns:
        capacity_factor.drop('plant_id_eia_y', axis=1, inplace=True)

    return(capacity_factor)


def eia_operator_plants(operator_id, pudl_engine):
    """Return all the EIA plant IDs associated with a given EIA operator ID."""
    Session = sa.orm.sessionmaker()
    Session.configure(bind=pudl_engine)
    session = Session()
    pudl_plant_ids = [p.plant_id for p in session.query(models.UtilityEIA923).
                      filter_by(operator_id=operator_id).
                      first().util_pudl.plants]
    eia923_plant_ids = [p.plant_id for p in
                        session.query(models.PlantEIA923).
                        filter(models.
                               PlantEIA923.
                               plant_id_pudl.
                               in_(pudl_plant_ids))]
    session.close_all()
    return(eia923_plant_ids)


def consolidate_ferc1_expns(steam_df, min_capfac=0.6, min_corr=0.5):
    """
    Calculate non-fuel production & nonproduction costs from a steam DataFrame.

    Takes a DataFrame containing information from the plants_steam_ferc1 table
    and add columns representing the non-production costs, and non-fuel
    production costs, which are sums of other expense columns. Which columns
    are treated as production vs. non-production costs is determined based on
    the overall correlation between those column values and net_generation_mwh
    for the entire steam_df DataFrame.

    Args:
        steam_df (DataFrame): Data selected from the PUDL plants_steam_ferc1
            table, containing expense columns, prefixed with expns_
        min_capfac (float): Minimum capacity factor required for a plant's
            data to be used in determining which expense columns are
            production vs. non-production costs.
        min_corr (float): Minimum correlation with net_generation_mwh required
            to indicate that a given expense field should be considered a
            "production" cost.

    Returns:
        DataFrame containing all the same information as the original steam_df,
            but with two additional columns consolidating the non-fuel
            production and non-production costs for ease of calculation.
    """
    steam_df = steam_df.copy()
    # Calculate correlation of expenses to net power generation. Require a
    # minimum plant capacity factor of 0.6 so we the signal will be high,
    # but we'll still have lots of plants to look at:
    expns_corr = ferc1_expns_corr(steam_df, min_capfac=min_capfac)

    # We've already got fuel separately, and we know it's a production expense
    expns_corr.pop('expns_fuel')
    # Sort these expense fields into nonfuel production (nonfuel_px) or
    # non-production (npx) expenses.
    nonfuel_px = [k for k in expns_corr.keys() if expns_corr[k] >= min_corr]
    npx = [k for k in expns_corr.keys() if expns_corr[k] < min_corr]

    # The three main categories of expenses we're reporting:
    # - fuel production expenses (already in the table)
    # - non-fuel production expenses
    steam_df['expns_total_nonfuel_production'] = \
        steam_df[nonfuel_px].copy().sum(axis=1)
    # - non-production expenses
    steam_df['expns_total_nonproduction'] = steam_df[npx].copy().sum(axis=1)

    return(steam_df)


def ferc1_expns_corr(steam_df, min_capfac=0.6):
    """
    Calculate generation vs. expense correlation for FERC Form 1 plants.

    This function helped us identify which of the expns_* fields in the FERC
    Form 1 dataset represent production costs, and which are non-production
    costs, for the purposes of modeling marginal cost of electricity from
    various plants.  We expect the difference in expenses vs. generation to
    be more indicative of production vs. non-production costs for plants with
    higher capacity factors, and since what we're trying to do here is
    identify which *fields* in the FERC Form 1 data are production costs, we
    allow a capacity_factor threshold to be set -- analysis is only done for
    those plants with capacity factors larger than the threshold.

    Additionaly, some types of plants simply do not have some types of
    expenses, so to keep those plants from dragging down otherwise meaningful
    correlations, any zero expense values are dropped before calculating the
    correlations.

    Returns a dictionary with expns_ field names as the keys, and correlations
    as the values.
    """
    steam_df = steam_df.copy()
    steam_df['capacity_factor'] = \
        (steam_df['net_generation_mwh'] / 8760 * steam_df['total_capacity_mw'])

    # Limit plants by capacity factor
    steam_df = steam_df[steam_df['capacity_factor'] > min_capfac]

    # This is all the expns_* fields, except for the per_mwh and total.
    cols_to_correlate = ['expns_operations',
                         'expns_fuel',
                         'expns_coolants',
                         'expns_steam',
                         'expns_steam_other',
                         'expns_transfer',
                         'expns_electric',
                         'expns_misc_power',
                         'expns_rents',
                         'expns_allowances',
                         'expns_engineering',
                         'expns_structures',
                         'expns_boiler',
                         'expns_plants',
                         'expns_misc_steam']

    expns_corr = {}
    for expns in cols_to_correlate:
        mwh_plants = steam_df.net_generation_mwh[steam_df[expns] != 0]
        expns_plants = steam_df[expns][steam_df[expns] != 0]
        expns_corr[expns] = np.corrcoef(mwh_plants, expns_plants)[0, 1]

    return(expns_corr)


def ferc_expenses(pudl_engine, pudl_plant_ids=[], require_eia=True,
                  min_capfac=0.6, min_corr=0.5):
    """
    Gather operating expense data for a selection of FERC plants by PUDL ID.

    Args:
        pudl_engine: a connection to the PUDL database.
        pudl_plant_ids: list of PUDL plant IDs for which to pull expenses out
            of the FERC dataset. If it's an empty list, get all the plants.
        require_eia: Boolean (True/False). If True, then only return FERC
            plants which also appear in the EIA dataset.  Useful for when you
            want to merge the FERC expenses with other EIA data.
        min_capfac: the minimum plant capacity factor to use in
            determining whether an expense category is a production or
            non-production cost.
        min_corr: The threhold correlation to use in determining whether an
            expense is a production or non-production expense. If an expense
            has a correlation to net generation that is greater than or equal
            to this threshold, it is categorized as a production expense.

    Returns:
        ferc1_expns_corr: A dictionary of expense categories
            and their correlations to the plant's net electricity
            generation.
        steam_df: a dataframe with all the operating expenses
            broken out for each simple FERC PUDL plant.
    """
    # All of the large steam plants from FERC:
    steam_df = outputs.plants_steam_ferc1(pudl_engine)

    # Calculate the dataset-wide expense correlations, for the record.
    expns_corrs = ferc1_expns_corr(steam_df, min_capfac=min_capfac)
    # Lump the operating expenses based on those correlations. Note that we
    # could also do this lumping after limiting the set of plants that we're
    # reporting on.  However, doing it based on the entire dataset seems more
    # appropriate, given that these correlations are properties of the fields,
    # not the plants... or so we hope.
    steam_df = consolidate_ferc1_expns(steam_df,
                                       min_capfac=min_capfac,
                                       min_corr=min_corr)

    # If we are only looking at a specified subset of the FERC plants, then
    # here is where we limit the information that's returned:
    if len(pudl_plant_ids) > 0:
        steam_df = steam_df[steam_df.plant_id_pudl.isin(pudl_plant_ids)]

    if require_eia:
        # All of the EIA PUDL plant IDs
        eia_pudl = eia_pudl_plant_ids(pudl_engine)
        steam_df = steam_df[
            steam_df.plant_id_pudl.isin(eia_pudl.plant_id_pudl)]

    # Pass back both the expense correlations, and the plant data.
    return(expns_corrs, steam_df)


def fuel_ferc1_by_pudl(pudl_plant_ids, pudl_engine,
                       fuels=['gas', 'oil', 'coal'],
                       cols=['fuel_consumed_total_mmbtu',
                             'fuel_consumed_total_cost_mmbtu',
                             'fuel_consumed_total_cost_unit']):
    """Aggregate FERC Form 1 fuel data by PUDL plant id and, optionally, fuel.

    Arguments:
        pudl_plant_ids: which PUDL plants should we retain for aggregation?
        fuels: Should the columns listed in cols be broken out by each
            individual fuel? If so, which fuels do we want totals for? If
            you want all fuels lumped together, pass in 'all'.
        cols: which columns from the fuel_ferc1 table should be summed.
    Returns:
        fuel_df: a dataframe with pudl_plant_id, year, and the summed values
            specified in cols. If fuels is not 'all' then it also has a column
            specifying fuel type.
    """
    fuel_df = outputs.fuel_ferc1_df(pudl_engine)

    # Calculate the total fuel heat content for the plant by fuel
    fuel_df = fuel_df[fuel_df.plant_id_pudl.isin(pudl_plant_ids)]

    if (fuels == 'all'):
        cols_to_gb = ['plant_id_pudl', 'report_year']
    else:
        # Limit to records that pertain to our fuels of interest.
        fuel_df = fuel_df[fuel_df['fuel'].isin(fuels)]
        # Group by fuel as well, so we get individual fuel totals.
        cols_to_gb = ['plant_id_pudl', 'report_year', 'fuel']

    fuel_df = fuel_df.groupby(cols_to_gb)[cols].sum()
    fuel_df = fuel_df.reset_index()

    return(fuel_df)


def steam_ferc1_by_pudl(pudl_plant_ids, pudl_engine,
                        cols=['net_generation_mwh', ]):
    """Aggregate and return data from the steam_ferc1 table by pudl_plant_id.

    Arguments:
        pudl_plant_ids: A list of ids to include in the output.
        cols: The data columns that you want to aggregate and return.
    Returns:
        steam_df: A dataframe with columns for report_year, pudl_plant_id and
            cols, with the values in cols aggregated by plant and year.
    """
    steam_df = outputs.plants_steam_ferc1_df(pudl_engine)
    steam_df = steam_df[steam_df.plant_id_pudl.isin(pudl_plant_ids)]
    steam_df = steam_df.groupby(['plant_id_pudl', 'report_year'])[cols].sum()
    steam_df = steam_df.reset_index()

    return(steam_df)


def frc_by_pudl(pudl_plant_ids, pudl_engine,
                fuels=['gas', 'oil', 'coal'],
                cols=['total_fuel_cost', ]):
    """
    Aggregate fuel_receipts_costs_eia923 table for comparison with FERC Form 1.

    In order to correlate information between EIA 923 and FERC Form 1, we need
    to aggregate the EIA data annually, and potentially by fuel. This function
    groups fuel_receipts_costs_eia923 by pudl_plant_id, fuel, and year, and
    sums the columns of interest specified in cols, and returns a dataframe
    with the totals by pudl_plant_id, fuel, and year.

    Args:
        pudl_plant_ids: list of plant IDs to keep.
        fuels: list of fuel strings that we want to group by. Alternatively,
            this can be set to 'all' in which case fuel is not grouped by.
        cols: List of data columns which we are summing.
    Returns:
        A dataframe with the sums of cols, as grouped by pudl ID, year, and
            (optionally) fuel.
    """
    # Get all the EIA info from generation_fuel_eia923
    frc_df = outputs.frc_eia923_df(pudl_engine)
    # Limit just to the plants we're looking at
    frc_df = frc_df[frc_df.plant_id_pudl.isin(pudl_plant_ids)]
    # Just keep the columns we need for output:
    cols_to_keep = ['plant_id_pudl', 'report_date']
    cols_to_keep = cols_to_keep + cols
    cols_to_gb = [pd.Grouper(freq='A'), 'plant_id_pudl']

    if (fuels != 'all'):
        frc_df = frc_df[frc_df.fuel.isin(fuels)]
        cols_to_keep = cols_to_keep + ['fuel', ]
        cols_to_gb = cols_to_gb + ['fuel', ]

    # Pare down the dataframe to make it easier to play with:
    frc_df = frc_df[cols_to_keep]

    # Prepare to group annually
    frc_df['report_date'] = pd.to_datetime(frc_df['report_date'])
    frc_df.index = frc_df.report_date
    frc_df.drop('report_date', axis=1, inplace=True)

    # Group and sum of the columns of interest:
    frc_gb = frc_df.groupby(by=cols_to_gb)
    frc_totals_df = frc_gb[cols].sum()

    # Simplify and clean the DF for return:
    frc_totals_df = frc_totals_df.reset_index()
    frc_totals_df['report_year'] = frc_totals_df.report_date.dt.year
    frc_totals_df = frc_totals_df.drop('report_date', axis=1)
    frc_totals_df = frc_totals_df.dropna()

    return(frc_totals_df)


def gen_fuel_by_pudl(pudl_plant_ids, pudl_engine,
                     fuels=['gas', 'oil', 'coal'],
                     cols=['fuel_consumed_total_mmbtu',
                           'net_generation_mwh']):
    """
    Aggregate generation_fuel_eia923 table for comparison with FERC Form 1.

    In order to correlate informataion between EIA 923 and FERC Form 1, we need
    to aggregate the EIA data annually, and potentially by fuel. This function
    groups generation_fuel_eia923 by pudl_plant_id, fuel, and year, and sums
    the columns of interest specified in cols, and returns a dataframe with
    the totals by pudl_plant_id, fuel, and year.

    Args:
        pudl_plant_ids: list of plant IDs to keep.
        fuels: list of fuel strings that we want to group by. Alternatively,
            this can be set to 'all' in which case fuel is not grouped by.
        cols: List of data columns which we are summing.
    Returns:
        A dataframe with the sums of cols, as grouped by pudl ID, year, and
            (optionally) fuel.
    """
    # Get all the EIA info from generation_fuel_eia923
    gf_df = outputs.gf_eia923_df(pudl_engine)

    # Standardize the fuel codes (need to fix this in the DB!!!!)
    gf_df = gf_df.rename(columns={'fuel_type_pudl': 'fuel'})
    # gf_df['fuel'] = gf_df.fuel.replace(to_replace='petroleum', value='oil')

    # Select only the records that pertain to our target IDs
    gf_df = gf_df[gf_df.plant_id_pudl.isin(pudl_plant_ids)]

    cols_to_keep = ['plant_id_pudl', 'report_date']
    cols_to_keep = cols_to_keep + cols
    cols_to_gb = [pd.Grouper(freq='A'), 'plant_id_pudl']

    if (fuels != 'all'):
        gf_df = gf_df[gf_df.fuel.isin(fuels)]
        cols_to_keep = cols_to_keep + ['fuel', ]
        cols_to_gb = cols_to_gb + ['fuel', ]

    # Pare down the dataframe to make it easier to play with:
    gf_df = gf_df[cols_to_keep]

    # Prepare to group annually
    gf_df['report_date'] = pd.to_datetime(gf_df['report_date'])
    gf_df.index = gf_df.report_date
    gf_df.drop('report_date', axis=1, inplace=True)

    gf_gb = gf_df.groupby(by=cols_to_gb)
    gf_totals_df = gf_gb[cols].sum()
    gf_totals_df = gf_totals_df.reset_index()

    # Simplify date info for easy comparison with FERC.
    gf_totals_df['report_year'] = gf_totals_df.report_date.dt.year
    gf_totals_df = gf_totals_df.drop('report_date', axis=1)
    gf_totals_df = gf_totals_df.dropna()

    return(gf_totals_df)


def generator_proportion_eia923(g, id_col='plant_id_eia'):
    """
    Generate a dataframe with the proportion of generation for each generator.

    Args:
        g: a dataframe from either all of generation_eia923 or some subset of
        records from generation_eia923. The dataframe needs the following
        columns to be present:
            plant_id, generator_id, report_date, net_generation_mwh

    Returns: a dataframe with:
            report_year, plant_id, generator_id, proportion_of_generation
    """
    # Set the datetimeindex
    g = g.set_index(pd.DatetimeIndex(g['report_year']))
    # groupby plant_id and by year
    g_yr = g.groupby([pd.Grouper(freq='A'), id_col, 'generator_id'])
    # sum net_gen by year by plant
    g_net_generation_per_generator = pd.DataFrame(
        g_yr.net_generation_mwh.sum())
    g_net_generation_per_generator = \
        g_net_generation_per_generator.reset_index(level=['generator_id'])

    # groupby plant_id and by year
    g_net_generation_per_plant = g.groupby(
        [pd.Grouper(freq='A'), id_col])
    # sum net_gen by year by plant and convert to datafram
    g_net_generation_per_plant = pd.DataFrame(
        g_net_generation_per_plant.net_generation_mwh.sum())

    # Merge the summed net generation by generator with the summed net
    # generation by plant
    g_gens_proportion = g_net_generation_per_generator.merge(
        g_net_generation_per_plant, how="left", left_index=True,
        right_index=True)
    g_gens_proportion['proportion_of_generation'] = (
        g_gens_proportion.net_generation_mwh_x /
        g_gens_proportion.net_generation_mwh_y)
    # Remove the net generation columns
    g_gens_proportion = g_gens_proportion.drop(
        ['net_generation_mwh_x', 'net_generation_mwh_y'], axis=1)
    g_gens_proportion.reset_index(inplace=True)

    return(g_gens_proportion)


def capacity_proportion_eia923(g, id_col='plant_id_eia',
                               capacity='nameplate_capacity_mw'):
    """
    Generate dataframe with proportion of plant capacity for each generator.

    Args:
        g: a dataframe from either all of generation_eia923 or some subset of
        records from generation_eia923. The dataframe needs the following
        columns to be present:
            generator_id, report_date, nameplate_capacity_mw

        id_col: either plant_id_eia (default) or plant_id_pudl
        capacity: nameplate_capacity_mw (default), summer_capacity_mw,
            or winter_capacity_mw

    Returns: a dataframe with:
            report_year, plant_id, generator_id, proportion_of_capacity
    """
    # groupby plant_id and by year
    g_net_capacity_per_plant = g.groupby(['report_year', id_col])
    # sum net_gen by year by plant and convert to datafram
    g_net_capacity_per_plant = pd.DataFrame(
        g_net_capacity_per_plant.nameplate_capacity_mw.sum())
    g_net_capacity_per_plant.reset_index(inplace=True)

    # Merge the summed net generation by generator with the summed net
    # generation by plant
    g_capacity_proportion = g.merge(
        g_net_capacity_per_plant, on=[id_col, 'report_year'], how="left")
    g_capacity_proportion['proportion_of_plant_capacity'] = (
        g_capacity_proportion.nameplate_capacity_mw_x /
        g_capacity_proportion.nameplate_capacity_mw_y)
    # Remove the net generation columns
    g_capacity_proportion = g_capacity_proportion.rename(
        columns={'nameplate_capacity_mw_x': 'nameplate_capacity_gen_mw',
                 'nameplate_capacity_mw_y': 'nameplate_capacity_plant_mw'})

    return(g_capacity_proportion)


def values_by_generator_eia923(table_eia923, column_name, g):
    """
    Generate a dataframe with a plant value proportioned out by generator.

    Args:
        table_eia923: an EIA923 table (this has been tested with
        fuel_receipts_costs_eia923 and generation_fuel_eia923).
        column_name: a column name from the table_eia923.
        g: a dataframe from either all of generation_eia923 or some subset of
        records from generation_eia923. The dataframe needs the following
        columns to be present:
            plant_id, generator_id, report_date, and net_generation_mwh.

    Returns: a dataframe with report_date, plant_id, generator_id, and the
        proportioned value from the column_name.
    """
    # Set the datetimeindex
    table_eia923 = table_eia923.set_index(
        pd.DatetimeIndex(table_eia923['report_date']))
    # groupby plant_id and by year
    table_eia923_gb = table_eia923.groupby(
        [pd.Grouper(freq='A'), 'plant_id'])
    # sum fuel cost by year by plant
    table_eia923_sr = table_eia923_gb[column_name].sum()
    # Convert back into a dataframe
    table_eia923_df = pd.DataFrame(table_eia923_sr)
    column_name_by_plant = "{}_plant".format(column_name)
    table_eia923_df = table_eia923_df.rename(
        columns={column_name: column_name_by_plant})
    # get the generator proportions
    g_gens_proportion = generator_proportion_eia923(g)
    # merge the per generator proportions with the summed fuel cost
    g_generator = g_gens_proportion.merge(
        table_eia923_df, how="left", right_index=True, left_index=True)
    # calculate the proportional fuel costs
    g_generator["{}_generator".format(column_name)] = (
        g_generator[column_name_by_plant] *
        g_generator.proportion_of_generation)
    # drop the unneccessary columns
    g_generator = g_generator.drop(
        ['proportion_of_generation', column_name_by_plant], axis=1)
    return(g_generator)


def primary_fuel_ferc1(fuel_df, fuel_thresh=0.5):
    """
    Determine the primary fuel for plants listed in the PUDL fuel_ferc1 table.

    Given a selection of records from the PUDL fuel_ferc1 table, determine
    the primary fuel type for each plant (as identified by a unique
    combination of report_year, respondent_id, and plant_name).

    Args:
        fuel_df (DataFrame): a DataFrame selected from the PUDL fuel_ferc1
            table, with columns including report_year, respondent_id,
            plant_name, fuel, fuel_qty_burned, and fuel_avg_mmbtu_per_unit.
        fuel_thresh (float): What is the minimum proportion of a plant's
            annual fuel consumption in terms of heat content, that a fuel
            must account for, in order for that fuel to be considered the
            primary fuel.

    Returns:
        plants_by_primary_fuel (DataFrame): a DataFrame containing report_year,
            respondent_id, plant_name, and primary_fuel.
    """
    plants_by_heat = plant_fuel_proportions_ferc1(fuel_df)

    # On a per plant, per year basis, identify the fuel that made the largest
    # contribution to the plant's overall heat content consumed. If that
    # proportion is greater than fuel_thresh, set the primary_fuel to be
    # that fuel.  Otherwise, leave it None.
    plants_by_heat = plants_by_heat.set_index(['report_year',
                                               'respondent_id',
                                               'plant_name'])
    plants_by_heat = plants_by_heat.drop('total_mmbtu', axis=1)
    mask = plants_by_heat >= fuel_thresh
    plants_by_heat = plants_by_heat.where(mask)
    plants_by_heat['primary_fuel'] = plants_by_heat.idxmax(axis=1)
    return(plants_by_heat[['primary_fuel', ]].reset_index())


def plant_fuel_proportions_ferc1(fuel_df):
    """Calculate annual fuel proportions by plant based on FERC data."""
    fuel_df = fuel_df.copy()

    fuel_df['total_mmbtu'] = \
        fuel_df['fuel_qty_burned'] * fuel_df['fuel_avg_mmbtu_per_unit']

    heat_df = fuel_df[['report_year',
                       'respondent_id',
                       'plant_name',
                       'fuel',
                       'total_mmbtu']]

    heat_pivot = heat_df.pivot_table(
        index=['report_year', 'respondent_id', 'plant_name'],
        columns='fuel',
        values='total_mmbtu')

    heat_pivot['total'] = heat_pivot.sum(axis=1, numeric_only=True)
    mmbtu_total = heat_pivot.copy()
    mmbtu_total = pd.DataFrame(mmbtu_total['total'])

    heat_pivot = heat_pivot.fillna(value=0)
    heat_pivot = heat_pivot.divide(heat_pivot.total, axis='index')
    heat_pivot = heat_pivot.drop('total', axis=1)
    heat_pivot = heat_pivot.reset_index()

    heat_pivot = heat_pivot.merge(mmbtu_total.reset_index())
    heat_pivot.rename(columns={'total': 'total_mmbtu'},
                      inplace=True)
    del heat_pivot.columns.name

    return(heat_pivot)


def plant_fuel_proportions_frc_eia923(frc_df, id_col='plant_id_eia'):
    """Calculate annual fuel proportions by plant from EIA923 fuel receipts."""
    frc_df = frc_df.copy()

    # Add a column with total fuel heat content per delivery
    frc_df['total_mmbtu'] = frc_df.fuel_quantity * frc_df.average_heat_content

    # Drop everything but report_date, plant_id, fuel_group, total_mmbtu
    frc_df = frc_df[['report_date', 'plant_id_eia',
                     'plant_id_pudl', 'fuel_group', 'total_mmbtu']]

    # Group by report_date(annual), plant_id, fuel_group
    frc_gb = frc_df.groupby(
        [id_col, pd.Grouper(freq='A'), 'fuel_group'])

    # Add up all the MMBTU for each plant & year. At this point each record
    # in the dataframe contains only information about a single fuel.
    heat_df = frc_gb.agg(np.sum)

    # Simplfy the DF a little before we turn it into a pivot table.
    heat_df = heat_df.reset_index()
    heat_df['year'] = pd.DatetimeIndex(heat_df['report_date']).year
    heat_df = heat_df.drop('report_date', axis=1)

    # Take the individual rows organized by fuel_group, and turn them into
    # columns, each with the total MMBTU for that fuel, year, and plant.
    heat_pivot = heat_df.pivot_table(
        index=['year', id_col],
        columns='fuel_group',
        values='total_mmbtu')

    # Add a column that has the *total* heat content of all fuels:
    heat_pivot['total'] = heat_pivot.sum(axis=1, numeric_only=True)

    # Replace any NaN values we got from pivoting with zeros.
    heat_pivot = heat_pivot.fillna(value=0)

    # Divide all columns by the total heat content, giving us the proportions
    # for each fuel instead of the heat content.
    heat_pivot = heat_pivot.divide(heat_pivot.total, axis='index')

    # Drop the total column (it's nothing but 1.0 values) and clean up the
    # index and columns a bit before returning the DF.
    heat_pivot = heat_pivot.drop('total', axis=1)
    heat_pivot = heat_pivot.reset_index()
    del heat_pivot.columns.name

    return(heat_pivot)


def primary_fuel_frc_eia923(frc_df, id_col='plant_id_eia', fuel_thresh=0.5):
    """Determine a plant's primary fuel from EIA923 fuel receipts table."""
    frc_df = frc_df.copy()

    # Figure out the heat content proportions of each fuel received:
    frc_by_heat = plant_fuel_proportions_frc_eia923(frc_df)

    # On a per plant, per year basis, identify the fuel that made the largest
    # contribution to the plant's overall heat content consumed. If that
    # proportion is greater than fuel_thresh, set the primary_fuel to be
    # that fuel.  Otherwise, leave it None.
    frc_by_heat = frc_by_heat.set_index([id_col, 'year'])
    mask = frc_by_heat >= fuel_thresh
    frc_by_heat = frc_by_heat.where(mask)
    frc_by_heat['primary_fuel'] = frc_by_heat.idxmax(axis=1)
    return(frc_by_heat[['primary_fuel', ]].reset_index())


def plant_fuel_proportions_gf_eia923(gf_df):
    """Calculate annual fuel proportions by plant from EIA923 gen fuel."""
    gf_df = gf_df.copy()

    # Drop everything but report_date, plant_id, fuel_group, total_mmbtu
    gf_df = gf_df[['report_date',
                   'plant_id',
                   'fuel_type_pudl',
                   'fuel_consumed_total_mmbtu']]

    # Set report_date as a DatetimeIndex
    gf_df = gf_df.set_index(pd.DatetimeIndex(gf_df['report_date']))

    # Group by report_date(annual), plant_id, fuel_group
    gf_gb = gf_df.groupby(
        ['plant_id', pd.Grouper(freq='A'), 'fuel_type_pudl'])

    # Add up all the MMBTU for each plant & year. At this point each record
    # in the dataframe contains only information about a single fuel.
    heat_df = gf_gb.agg(np.sum)

    # Simplfy the DF a little before we turn it into a pivot table.
    heat_df = heat_df.reset_index()
    heat_df['year'] = pd.DatetimeIndex(heat_df['report_date']).year
    heat_df = heat_df.drop('report_date', axis=1)

    # Take the individual rows organized by fuel_group, and turn them into
    # columns, each with the total MMBTU for that fuel, year, and plant.
    heat_pivot = heat_df.pivot_table(
        index=['year', 'plant_id'],
        columns='fuel_type_pudl',
        values='fuel_consumed_total_mmbtu')

    # Add a column that has the *total* heat content of all fuels:
    heat_pivot['total'] = heat_pivot.sum(axis=1, numeric_only=True)

    # Replace any NaN values we got from pivoting with zeros.
    heat_pivot = heat_pivot.fillna(value=0)

    # Divide all columns by the total heat content, giving us the proportions
    # for each fuel instead of the heat content.
    heat_pivot = heat_pivot.divide(heat_pivot.total, axis='index')

    # Drop the total column (it's nothing but 1.0 values) and clean up the
    # index and columns a bit before returning the DF.
    heat_pivot = heat_pivot.drop('total', axis=1)
    heat_pivot = heat_pivot.reset_index()
    del heat_pivot.columns.name

    return(heat_pivot)


def primary_fuel_gf_eia923(gf_df, id_col='plant_id_eia', fuel_thresh=0.5):
    """Determine a plant's primary fuel from EIA923 generation fuel table."""
    gf_df = gf_df.copy()

    # Figure out the heat content proportions of each fuel received:
    gf_by_heat = plant_fuel_proportions_gf_eia923(gf_df)

    # On a per plant, per year basis, identify the fuel that made the largest
    # contribution to the plant's overall heat content consumed. If that
    # proportion is greater than fuel_thresh, set the primary_fuel to be
    # that fuel.  Otherwise, leave it None.
    gf_by_heat = gf_by_heat.set_index([id_col, 'report_year'])
    mask = gf_by_heat >= fuel_thresh
    gf_by_heat = gf_by_heat.where(mask)
    gf_by_heat['primary_fuel'] = gf_by_heat.idxmax(axis=1)
    return(gf_by_heat[['primary_fuel', ]].reset_index())


def fercplants(plant_tables=['f1_steam',
                             'f1_gnrt_plant',
                             'f1_hydro',
                             'f1_pumped_storage'],
               years=constants.working_years['ferc1'],
               new=True,
               min_capacity=5.0):
    """
    Generate a list of FERC plants for matching with EIA plants.

    There are several kinds of FERC plants, with different information stored
    in different FERC database tables. FERC doesn't provide any kind of
    plant_id like EIA, so the unique identifier that we're using is a
    combination of the respondent_id (the utility) and plant_name.

    For each table in the FERC DB that contains per-plant information, we'll
    grab the respondent_id and plant_name, and join that with respondent_name
    so that the utility is more readily identifiable.  We'll also add a column
    indicating what table the plant came from, and return a DataFrame with
    those four columns in it, for use in the matching. That matching currently
    happens in an Excel spreadsheet, so you will likely want to output the
    resulting DataFrame as a CSV or XLSX file.

    The function can generate an exhaustive list of plants, or it can only grab
    plants from a particular range of years. It can also optionally grab only
    new plants i.e. those which do not appear in the existing PUDL database.
    This is useful for finding new plants when a new year of FERC data comes
    out.

    Args:
        f1_tables (list): A list of tables in the FERC Form 1 DB whose plants
            you want to get information about.  Can include any of: f1_steam,
            f1_gnrt_plant, f1_hydro, and f1_pumped_storage.
        years (list): The set of years for which you wish to obtain plant by
            plant information.
        new (boolean): If True (the default) then return only those plants
            which appear in the years of FERC data being specified by years,
            and NOT also in the currently initialized PUDL DB.
        min_capacity (float): The smallest size plant, in MW, that should be
            included in the output. This avoids most of the plants being tiny.

    Returns:
        DataFrame: with four columns: respondent_id, respondent_name,
            plant_name, and plant_table.
    """
    # Need to be able to use years outside the "valid" range if we're trying
    # to get new plant ID info...
    if not new:
        for yr in years:
            assert yr in constants.working_years['ferc1']

    okay_tbls = ['f1_steam',
                 'f1_gnrt_plant',
                 'f1_hydro',
                 'f1_pumped_storage']

    # Function only knows how to work with these tables.
    for tbl in plant_tables:
        assert tbl in okay_tbls

    f1_engine = ferc1.db_connect_ferc1()

    # Need to make sure we have a populated metadata object, which isn't
    # always the case, since folks often are not initializing the FERC DB.
    ferc1.define_db(max(constants.working_years['ferc1']),
                    constants.ferc1_working_tables,
                    ferc1.ferc1_meta)
    f1_tbls = ferc1.ferc1_meta.tables

    # FERC doesn't use the sme column names for the same values across all of
    # Their tables... but all of these are cpacity in MW.
    capacity_cols = {'f1_steam': 'tot_capacity',
                     'f1_gnrt_plant': 'capacity_rating',
                     'f1_hydro': 'tot_capacity',
                     'f1_pumped_storage': 'tot_capacity'}

    rspndnt_tbl = f1_tbls['f1_respondent_id']
    ferc1_plants_all = pd.DataFrame()
    for tbl in plant_tables:
        plant_select = sa.sql.select([
            f1_tbls[tbl].c.respondent_id,
            f1_tbls[tbl].c.plant_name,
            rspndnt_tbl.c.respondent_name
        ]).distinct().where(
            sa.and_(
                f1_tbls[tbl].c.respondent_id == rspndnt_tbl.c.respondent_id,
                f1_tbls[tbl].c.plant_name != '',
                f1_tbls[tbl].columns[capacity_cols[tbl]] >= min_capacity,
                f1_tbls[tbl].c.report_year.in_(years)
            )
        )
        # Add all the plants from the current table to our bigger list:
        new_plants = pd.read_sql(plant_select, f1_engine)
        new_plants.respondent_name = new_plants.respondent_name.str.strip()
        new_plants.respondent_name = new_plants.respondent_name.str.title()
        new_plants.plant_name = new_plants.plant_name.str.strip().str.title()
        new_plants['plant_table'] = tbl
        ferc1_plants_all = ferc1_plants_all.append(
            new_plants[['respondent_id',
                        'respondent_name',
                        'plant_name',
                        'plant_table']]
        )

    # If we're only trying to get the NEW plants, then we need to see which
    # ones we've already got in the PUDL DB, and look at what's different.
    if(new):
        ferc1_plants_all = ferc1_plants_all.set_index(
            ['respondent_id', 'plant_name'])

        pudl_engine = pudl.db_connect_pudl()
        pudl_tbls = pudl.models.PUDLBase.metadata.tables

        ferc1_plants_tbl = pudl_tbls['plants_ferc']
        ferc1_plants_select = sa.sql.select([
            ferc1_plants_tbl.c.respondent_id,
            ferc1_plants_tbl.c.plant_name
        ]).distinct()
        ferc1_plants_old = pd.read_sql(ferc1_plants_select, pudl_engine)
        ferc1_plants_old = ferc1_plants_old.set_index(
            ['respondent_id', 'plant_name'])

        # Take the difference between the two table indexes -- I.e. get a
        # list of just the index values that appear in the FERC index, but
        # not in the PUDL index.
        new_index = ferc1_plants_all.index.difference(ferc1_plants_old.index)
        ferc1_plants = ferc1_plants_all.loc[new_index].reset_index()
    else:
        ferc1_plants = ferc1_plants_all

    return(ferc1_plants)
