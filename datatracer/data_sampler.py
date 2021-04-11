# -*- coding: utf-8 -*-

"""DataTracer core module.

This module introduces tools for sampling from databases while respecting the row lineage.
"""
import sys

import random

from tqdm import tqdm

def calculate_size(transformed_dataset):
    size = 0
    for table in transformed_dataset.values():
        size += table['row_size'] * len(table['chosen'])
    return size

def transform_dataset(metadata, dataset):
    fks = metadata.get_foreign_keys()
    transformed_fk = {}
    for fk in fks:
        table, all_field, ref_table, all_ref_field = fk["table"], fk["field"], fk["ref_table"], fk["ref_field"]
        if isinstance(all_field, str):
            all_field = [all_field]
            all_ref_field = [all_ref_field]
        for field, ref_field in zip(all_field, all_ref_field):
            if ref_table not in transformed_fk:
                transformed_fk[ref_table] = []
            transformed_fk[ref_table].append((ref_table, ref_field, table, field))
    transformed_dataset = {}
    size = 0
    for table_name in dataset:
        table = dataset[table_name]
        columns = list(table.columns)
        transformed_table = {'size': table.memory_usage().sum(),
                             'row_size': float(table.memory_usage().sum()) / len(table),
                             'entries': {col: {} for col in columns},
                             'chosen': set(range(len(table))),}
        for idx in range(len(table)):
            for col in columns:
                val = table.iloc[idx][col]
                if val not in transformed_table['entries'][col]:
                    transformed_table['entries'][col][val] = []
                transformed_table['entries'][col][val].append(idx)
        transformed_dataset[table_name] = transformed_table
        size += transformed_table['size']
    return transformed_fk, transformed_dataset, size

def backward_transform(transformed_dataset, dataset):
    new_dataset = {}
    for table_name in dataset:
        idxes = list(transformed_dataset[table_name]['chosen'])
        new_dataset[table_name] = dataset[table_name].iloc[idxes]
    return new_dataset

def remove_row(dataset, transformed_fk, transformed_dataset, table_name, idx):
    if idx in transformed_dataset[table_name]['chosen']:
        transformed_dataset[table_name]['chosen'].remove(idx)
        if len(transformed_dataset[table_name]['chosen']) == 0:
            return None
    row = dataset[table_name].iloc[idx]
    if table_name in transformed_fk:
        for table, col, other_table, other_col in transformed_fk[table_name]:
            val = row[col]
            if val in transformed_dataset[other_table]['entries'][other_col]:
                for new_idx in transformed_dataset[other_table]['entries'][other_col][val]:
                    if new_idx in transformed_dataset[other_table]['chosen']:
                        if remove_row(dataset, transformed_fk, transformed_dataset, other_table, new_idx) is None:
                            return None
    return True

def get_root_tables(metadata):
    all_tables = {table['name'] for table in metadata.get_tables()}
    
    for fk in metadata.get_foreign_keys():
        if fk['table'] in all_tables:
            all_tables.remove(fk['table'])
    if len(all_tables) > 0:
        return all_tables
    else:
        return {table['name'] for table in metadata.get_tables()}

def sample_dataset(metadata, dataset, max_size=None, max_ratio=1.0, rand_seed=0):
    if len(dataset) == 0:
        return None #empty dataset
    
    random.seed(rand_seed)
    transformed_fk, transformed_dataset, size = transform_dataset(metadata, dataset)
    if max_size is not None:
        max_size *= (1024.0**2) #input max_size is in MB
    else:
        max_size = size
    target_size = min(max_size, size * float(max_ratio))
    root_tables = get_root_tables(metadata)
    while calculate_size(transformed_dataset) > target_size:
        table_name = random.sample(root_tables, 1)[0]
        if len(transformed_dataset[table_name]['chosen']) > 0:
            idx = random.sample(transformed_dataset[table_name]['chosen'], 1)[0]
            if remove_row(dataset, transformed_fk, transformed_dataset, table_name, idx) is None:
                return None
        else:
            return None
    
    return backward_transform(transformed_dataset, dataset)

def sample_datasets(dict_of_databases, max_size=None, max_ratio=1.0, rand_seed=0):
    sys.setrecursionlimit(10**6)
    iterator = tqdm(dict_of_databases.items())
    new_dict_of_databases = {}
    for database_name, (metadata, tables) in iterator:
        iterator.set_description("Sampling from %s" % database_name)
        new_tables = sample_dataset(metadata, tables, max_size=max_size, max_ratio=max_ratio, rand_seed=rand_seed)
        if new_tables is None:
            print("%s is dropped because of empty tables when sampling" % database_name)
        else:
            new_dict_of_databases[database_name] = (metadata, new_tables)
    return new_dict_of_databases