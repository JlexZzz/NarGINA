import copy
import json

import numpy as np
import torch
import torch_geometric as pyg

import OneForAll.utils as utils
from OneForAll.data.KG.gen_data import KGOFADataset
from OneForAll.data.chemmol.gen_data import MolOFADataset
from OneForAll.data.single_graph.gen_data import SingleGraphOFADataset
from OneForAll.fs_datamanager import SimpleFSManager
from OneForAll.gp.lightning.data_template import DataWithMeta
from OneForAll.ofa_datasets import (MultiDataset, GraphListHierDataset, SubgraphHierDataset,
                          SubgraphLinkHierDataset, SubgraphKGHierDataset, SubgraphNopromptDataset,
                          GraphListNopromptDataset, SubgraphNopromptLinkDataset, FewShotDataset)

# TODO: Instead of using global() to access these functions, come up with something more elegant
from OneForAll.gp.lightning.metric import (binary_auc_func, flat_binary_func, classification_func, EvalKit, )
from OneForAll.utils import (binary_apr_func, binary_auc_multi_func, binary_single_auc_func, classification_single_func,
                   flat_auc, )

name2dataset = {"arxiv": SingleGraphOFADataset, "Cora": SingleGraphOFADataset, "Pubmed": SingleGraphOFADataset,
                "WN18RR": KGOFADataset, "FB15K237": KGOFADataset, "wikics": SingleGraphOFADataset,
                "chemblpre": MolOFADataset, "chempcba": MolOFADataset, "chemhiv": MolOFADataset, "mydata":KGOFADataset,
                "my_data_lev_l2lev_n":SingleGraphOFADataset,"WN18RR_lev_l2lev_n":SingleGraphOFADataset,"my_data_lev_l2lev_n_no_negative":SingleGraphOFADataset,
                "mydata_no_negative":KGOFADataset
                }


########################################################################
# Dataset split functions, split datasets into train/valid/test splits #
########################################################################


def ArxivSplitter(dataset):
    return dataset.data.split


def ArxivFSSplitter(dataset):
    labels = dataset.data.y
    with open("data/low_resource_split.json", "r") as f:
        lr_class_split = json.load(f)
    arxiv_cls_split = lr_class_split["arxiv"]
    fs_split = []
    for split in arxiv_cls_split:
        cls_idx = []
        data_idx = []
        for cls in split:
            cls_idx.append(cls)
            cls_data_idx = (labels == cls).nonzero(as_tuple=True)[0]
            data_idx.append(cls_data_idx.numpy())
        fs_split.append([np.array(cls_idx), data_idx])
    return {"train": fs_split[0], "valid": fs_split[1], "test": fs_split[2]}


def CiteSplitter(dataset):
    text_g = dataset.data
    split = {"train": text_g.train_masks[0].nonzero(as_tuple=True)[0],
             "valid": text_g.val_masks[0].nonzero(as_tuple=True)[0],
             "test": text_g.test_masks[0].nonzero(as_tuple=True)[0], }
    return split


def CiteFSSplitter(dataset):
    labels = torch.tensor(dataset.data.y) if not isinstance(dataset.data.y, torch.Tensor) else dataset.data.y
    labels = labels.view(-1)
    cls_idx = []
    data_idx = []
    for i in range(labels.max() + 1):
        cls_idx.append(int(i))
        cls_data_idx = (labels == i).nonzero(as_tuple=True)[0]
        data_idx.append(cls_data_idx.numpy())
    cls_idx = np.array(cls_idx)
    return {k: [cls_idx, data_idx] for k in ["train", "valid", "test"]}


def CiteLinkSplitter(dataset):
    text_g = dataset.data
    edges = text_g.edge_index
    edge_perm = torch.randperm(len(edges[0]))
    train_offset = int(len(edge_perm) * 0.85)
    val_offset = int(len(edge_perm) * 0.9)
    edge_indices = {"train": edge_perm[:train_offset], "valid": edge_perm[train_offset:val_offset],
                    "test": edge_perm[val_offset:], }
    return edge_indices


def KGSplitter(dataset):
    converted_triplet = dataset.get_idx_split()
    split = {}
    count = 0
    for name in converted_triplet:
        split[name] = torch.arange(count, count + len(converted_triplet[name][0]))
        count += len(converted_triplet[name][0])
    return split


def KGFSTrainSplitter(dataset):
    converted_triplet = dataset.get_idx_split()
    all_types = torch.cat([torch.tensor(converted_triplet[k][1]) for k in converted_triplet])
    with open("data/low_resource_split.json", "r") as f:
        lr_class_split = json.load(f)
    fs_split = []
    for split in lr_class_split[dataset.name]:
        cls_idx = []
        data_idx = []
        for cls in split:
            cls_idx.append(cls)
            cls_data_idx = (all_types == cls).nonzero(as_tuple=True)[0]
            data_idx.append(cls_data_idx.numpy())
        fs_split.append([np.array(cls_idx), data_idx])
    return {"train": fs_split[0], "valid": fs_split[1], "test": fs_split[2]}


def KGFSSplitter(dataset):
    converted_triplet = dataset.get_idx_split()
    all_types = {k: torch.tensor(converted_triplet[k][1]) for k in converted_triplet}
    offset = ([0] + [len(all_types[k]) for k in all_types])[:-1]
    for i in range(1, len(offset)):
        offset[i] += offset[i - 1]
    all_types_torch = torch.cat([all_types[k] for k in all_types])
    n_types = all_types_torch.max() + 1
    fs_split = {}
    for idx, name in enumerate(converted_triplet):
        cls_idx = []
        data_idx = []
        for i in range(n_types):
            cls_idx.append(i)
            cls_data_idx = (all_types[name] == i).nonzero(as_tuple=True)[0] + offset[idx]
            data_idx.append(cls_data_idx.numpy())
        fs_split[name] = [np.array(cls_idx), data_idx]
    return fs_split


def WikiSplitter(dataset):
    text_g = dataset.data
    wiki_split_idx = 0
    split = {"train": torch.where(text_g.train_mask[:, wiki_split_idx])[0].numpy(),
             "valid": torch.where(text_g.val_mask[:, wiki_split_idx])[0].numpy(),
             "test": torch.where(text_g.test_mask)[0].numpy(), }
    return split

def MolSplitter(dataset):
    return dataset.get_idx_split()

def MolFSTrainSplitter(dataset):
    fs_split = {}
    # use all chemblepre classes as training classes for few-shot/zero-shot tasks
    all_classes = dataset.y.view(len(dataset), -1)
    positive_samples = [(cls==1).nonzero(as_tuple=True)[0] for cls in all_classes.T]
    negative_samples = [(cls==0).nonzero(as_tuple=True)[0] for cls in all_classes.T]
    all_idx2cls = [np.array([i for i in range(2 * len(positive_samples))]), negative_samples + positive_samples]
    fs_split['train'] = all_idx2cls
    fs_split['valid'] = all_idx2cls
    fs_split['test'] = all_idx2cls

    return fs_split


#############################################
#   Preprocessing functions                 #
#############################################

def LinkConstructGraph(dataset, split):
    text_g = dataset.data
    edges = text_g.edge_index
    graph_dict = text_g.to_dict()
    graph_dict["edge_index"] = edges[:, split["train"]]
    train_graph = pyg.data.Data(**graph_dict)
    return train_graph


def KGConstructEdgeList(dataset, split):
    converted_triplet = dataset.get_idx_split()
    all_edges = torch.cat([torch.tensor(converted_triplet[k][0]) for k in converted_triplet], dim=0)
    all_types = torch.cat([torch.tensor(converted_triplet[k][1]) for k in converted_triplet])
    if len(split["train"]) == 2:
        idx = np.concatenate(split["train"][1])
    else:
        idx = split["train"]
    graph_dict = dataset.data.to_dict()
    graph_dict["edge_index"] = all_edges[idx].T
    graph_dict["edge_types"] = all_types[idx]
    graph = pyg.data.Data(**graph_dict)
    return all_edges, all_types, graph


def make_data(name, data, split_name, metric, eval_func, num_classes, **kwargs):
    # Wrap GraphTextDataset with DataWithMeta for easy evaluator construction
    return DataWithMeta(data, kwargs["batch_size"], sample_size=kwargs["sample_size"], metric=metric,
                        state_name=split_name + "_" + name, classes=num_classes,
                        meta_data={"eval_func": eval_func, "eval_mode": kwargs["eval_mode"]}, )


######################################################
#   Construct GraphTextDataset                       #
######################################################

def ConstructNodeCls(dataset, split, split_name, prompt_feats, to_bin_cls_func, global_data, task_level, **kwargs):
    text_g = dataset.data

    return SubgraphHierDataset(text_g, prompt_feats["class_node_text_feat"], prompt_feats["prompt_edge_text_feat"],
                               prompt_feats["noi_node_text_feat"], split[split_name], to_undirected=True,
                               process_label_func=to_bin_cls_func, prompt_edge_list=dataset.get_edge_list(task_level),
                               **kwargs, )


def ConstructNodeNopromptCls(dataset, split, split_name, to_bin_cls_func, global_data, **kwargs):
    text_g = dataset.data

    return SubgraphNopromptDataset(text_g, text_g.label_text_feat, split[split_name], to_undirected=True,
                                   process_label_func=to_bin_cls_func, **kwargs, )


def ConstructLinkCls(dataset, split, split_name, prompt_feats, to_bin_cls_func, global_data, task_level, **kwargs):
    text_g = dataset.data
    edges = text_g.edge_index
    train_graph = global_data

    return SubgraphLinkHierDataset(train_graph, prompt_feats["class_node_text_feat"],
                                   prompt_feats["prompt_edge_text_feat"], prompt_feats["noi_node_text_feat"],
                                   edges.T[split[split_name]].numpy(), to_undirected=True, hop=3,
                                   process_label_func=to_bin_cls_func, prompt_edge_list=dataset.get_edge_list(task_level),
                                   **kwargs, )


def ConstructLinkNopromptCls(dataset, split, split_name, to_bin_cls_func, **kwargs):
    text_g = dataset.data
    edges = text_g.edge_index
    train_graph = kwargs["global_data"]

    return SubgraphNopromptLinkDataset(train_graph, train_graph.edge_label_feat, edges.T[split[split_name]].numpy(),
                                       prompt_feat=train_graph.prompt_text_edge_feat, to_undirected=True, hop=3,
                                       process_label_func=to_bin_cls_func, **kwargs, )


def ConstructKG(dataset, split, split_name, prompt_feats, to_bin_cls_func, task_level, global_data, **kwargs):
    edge_data = [global_data[0][split[split_name]].tolist(), global_data[1][split[split_name]].tolist()]
    # Fow lr_link tasks: use train class links to construct adj matrix for training
    if task_level == 'lr_link' and kwargs['fs_flag'] == 'train':
        fs_edges = global_data[0][split['train']].tolist()
    elif task_level == 'lr_link' and kwargs['fs_flag'] in ['valid', 'test']:
        fs_edges = global_data[0].tolist()
    else:
        fs_edges = None

    return SubgraphKGHierDataset(global_data[-1], prompt_feats["class_node_text_feat"],
                                 prompt_feats["prompt_edge_text_feat"], prompt_feats["noi_node_text_feat"], edge_data,
                                 to_undirected=True, hop=2, process_label_func=to_bin_cls_func,
                                 prompt_edge_list=dataset.get_edge_list(task_level), fs_edges=fs_edges, **kwargs, )


def ConstructMolCls(dataset, split, split_name, prompt_feats, to_bin_cls_func, task_level, global_data, **kwargs):
    return GraphListHierDataset(dataset, prompt_feats["class_node_text_feat"], prompt_feats["prompt_edge_text_feat"],
                                prompt_feats["noi_node_text_feat"], split[split_name],
                                process_label_func=to_bin_cls_func, prompt_edge_list=dataset.get_edge_list(task_level),
                                **kwargs, )


def ConstructMolNopromptCls(dataset, split, split_name, to_bin_cls_func, **kwargs):
    return GraphListNopromptDataset(dataset, dataset.label_text_feat, dataset.prompt_edge_feat, split[split_name],
                                    process_label_func=to_bin_cls_func, single_prompt_edge=True,
                                    walk_length=kwargs["walk_length"], )


def ConstructFSTask(dataset, split, split_name, prompt_feats, to_bin_cls_func, global_data, task_level, **kwargs):
    original_idx = np.concatenate(split[split_name][1])
    pseudo_split = {"pseudo": original_idx, "train": np.concatenate(split['train'][1])}
    query_idx = []
    count = 0
    for d in split[split_name][1]:
        query_idx.append(torch.arange(count, count + len(d), dtype=torch.long))
        count += len(d)

    query_graph_dataset = globals()[kwargs["base_construct"]](dataset=dataset, split=pseudo_split, split_name="pseudo",
                                                              prompt_feats=prompt_feats, to_bin_cls_func=to_bin_cls_func,
                                                              global_data=global_data, task_level=task_level, fs_flag=split_name, **kwargs)

    support_graph_dataset = globals()[kwargs["base_construct"]](dataset=dataset, split=pseudo_split,
                                                                split_name="pseudo", prompt_feats=prompt_feats,
                                                                to_bin_cls_func=to_bin_cls_func, global_data=global_data,
                                                                task_level=task_level, fs_flag=split_name, **kwargs)

    fs_loader = SimpleFSManager(split[split_name][0], query_idx, kwargs["k_shot"], 1, kwargs["n_way"],
                                kwargs.get("min_k_shot"), kwargs.get("min_n_way"), task_level,)

    return FewShotDataset(fs_loader, query_graph_dataset, support_graph_dataset,
                          prompt_feats["prompt_edge_text_feat"][-2:], task_level)



####################################
#   process_label_function         #
####################################

def process_pth_label(embs, label):
    binary_rep = torch.zeros((1, len(embs)))
    binary_rep[0, label.squeeze().to(torch.long)] = 1
    return label.view(1, -1).to(torch.long), embs, binary_rep


def process_reverse_binary_label(embs, label):
    binary_rep = torch.zeros((1, len(embs)))
    binary_rep[0, label.squeeze().to(torch.long)] = 1
    embs = embs[[1, 0]]
    return label.view(1, -1).to(torch.long), embs, binary_rep

def process_reverse_multi_label(embs, label):
    return (torch.tensor([[0]]), embs[[1, 0]], label,)


def process_multi_label(embs, label):
    valid_idx = label == label
    # valid_idx = torch.zeros_like(classes, dtype=torch.bool)
    return (
        torch.tensor([[0]]), embs[valid_idx.view(-1)].copy(), label[:, valid_idx.view(-1)].detach().clone(),)


def process_positive_negative_multi_label(embs, label):
    valid_idx = label == label
    label = label[:, valid_idx.view(-1)].detach().clone()
    valid_idx = valid_idx.repeat(1, 2)
    label = torch.cat([label, 1 - label], dim=-1)
    return (torch.tensor([[0]]), embs[valid_idx.view(-1)].copy(), label,)


def eval_process_label(embs, classes):
    return (torch.tensor([[0]]), embs, classes,)


def process_label_positive_only(embs, label):
    return torch.tensor([[0]]), embs[:len(label.view(-1))], label


def process_int_label(embs, label):
    binary_rep = torch.zeros((1, len(embs)))
    binary_rep[0, label] = 1
    return torch.tensor([label]).view(1, -1), embs, binary_rep

def process_fewshot_label(embs, label):
    trimed_class = torch.zeros((1, len(embs)))
    trimed_class[0, label] = 1
    return label, embs, trimed_class


def hiv_trim_class(embs, label):
    one_hot_label = torch.nn.functional.one_hot(label.to(torch.long), num_classes=2)
    return label, embs, one_hot_label


def hiv_zs_class(embs, label):
    # one_hot_label = torch.nn.functional.one_hot(
    #     label.to(torch.long), num_classes=2
    # )
    return label, embs[0:1], label


def gen_can(n_class, label, size):
    can = torch.randint(n_class, size)
    mask = torch.rand(size) > 0.75
    can[mask] = label.view(-1)
    return can


def process_logic_label(embs, label):
    num_class = int(np.sqrt(len(embs) / 2))
    can = gen_can(num_class, label, (4, 2))
    or_label = ((can == label.view(-1)).sum(-1) > 0).to(torch.int)
    or_feat = embs[can[:, 0] * num_class + can[:, 1]]

    can = gen_can(num_class, label, (4, 2))
    and_label = ((can == label.view(-1)).sum(-1) == 0).to(torch.int)
    and_feat = embs[can[:, 0] * num_class + can[:, 1] + num_class ** 2]
    new_class_emb = torch.cat([or_feat, and_feat], dim=0)
    new_binary_rep = torch.cat([or_label, and_label]).view(1, -1)
    if isinstance(label, int):
        label = torch.tensor(label)
    return label.view(1, -1).to(torch.long), new_class_emb, new_binary_rep


none_process_label = None


class UnifiedTaskConstructor:
    def __init__(self, tasks: list[str], load_texts: bool, encoder: utils.SentenceEncoder,
                 task_config_lookup: dict, data_config_lookup: dict, root="cache_data",
                 batch_size=256, sample_size=-1, eval_batch_size=None):
        """
        Construct tasks from a dictionary of dataset configurations. A task must contain a train dataset, but can
        have arbitrary number of valid/test dataset. A valid/test dataset is wrapped by a
        gp.lightning.data_template.DataWithMeta that contains information for evaluation metrics

        self.construct_exp construct all datasets.
        Args:
            tasks: a list of task names, they should be keys in the task_config_lookup
            load_texts: If true, only load raw texts instead of generated embedding.
            encoder: utils.SentenceEncoder
            task_config_lookup: a dictionary for tasks, more details in Readme
            data_config_lookup: a dictionary for datasets construction in Readme
            root: dataset loading directory
            batch_size: int
            sample_size: int, -1 means full dataste
            eval_batch_size: int, None means equal to batch_size.
        """
        self.root = root
        self.load_texts = load_texts
        self.tasks = tasks
        self.encoder = encoder
        self.task_config_lookup = task_config_lookup
        self.data_config_lookup = data_config_lookup
        self.batch_size = batch_size
        self.sample_size = sample_size
        self.eval_batch_size = (batch_size if eval_batch_size is None else eval_batch_size)
        with open("OneForAll/data/low_resource_split.json", "r") as f:
            self.lr_class_split = json.load(f)

        self.dataset = {}  # keyed by base dataset names e.g. cora, pubmed and not cora-link
        self.dataset_split = {}  # keyed by dataset names and task level e.g. cora_e2e_link
        self.preprocess_storage = {}  # keyed by dataset names and task level e.g. cora_e2e_link
        self.datamanager = {}
        self.edges = {}
        self.datasets = {"train": [], "valid": [],
                         "test": []}  # train a list of Dataset, valid/test a list of DataWithMeta
        self.stage_names = {"train": [], "valid": [], "test": []}

        self.if_subgraph = True

    def construct_exp(self):
        val_task_index_lst = []
        val_pool_mode = []
        for task in self.tasks:
            config = self.task_config_lookup[task]
            config = copy.deepcopy(config)
            val_task_index_lst.append(self.construct_task(config))
            val_pool_mode.append(config["eval_pool_mode"])
        return val_task_index_lst, val_pool_mode

    def construct_task(self, config):
        """
        Datasets in a task are described in config["eval_set_constructs"] that describe the stage (train/valid/test)
        of the dataset.
        """
        val_task_index = []
        for stage_config in config["eval_set_constructs"]:
            if "dataset" not in stage_config:
                stage_config["dataset"] = config["dataset"]
            dataset_name = stage_config["dataset"]

            assert dataset_name in self.data_config_lookup

            dataset_config = self.data_config_lookup[dataset_name]

            stage_ind = self.add_dataset(stage_config, dataset_config)

            if stage_config["stage"] == "valid":
                val_task_index.append(stage_ind)
        return val_task_index

    def get_split_key(self, dataset_config):
        return dataset_config["dataset_name"] + "_" + dataset_config["task_level"]

    def get_stage_name(self, stage_config, dataset_config):
        return "_".join([stage_config["dataset"], self.get_split_key(dataset_config), stage_config["stage"],
                         stage_config["split_name"]])

    def get_ofa_data(self, dataset_config):
        dataset_name = dataset_config["dataset_name"]
        if dataset_name not in self.dataset:
            self.dataset[dataset_name] = name2dataset[dataset_name](dataset_name, load_texts=self.load_texts,
                                                                    root=self.root, encoder=self.encoder)
        return self.dataset[dataset_name]

    def get_data_split(self, dataset_config):
        """
        Split data based on task_level
        """
        split_key = self.get_split_key(dataset_config)
        if split_key not in self.dataset_split:
            dataset_splitter = dataset_config.get("dataset_splitter")
            split = globals()[dataset_splitter](
                self.dataset[dataset_config["dataset_name"]]) if dataset_splitter else None
            self.dataset_split[split_key] = split
        return self.dataset_split[split_key]

    def get_global_data(self, dataset_config):
        """
        If global_data for a dataset is required, such as constructed train graph for link tasks, a preprocessing
        function is called and the returned values are stored.
        """
        split_key = self.get_split_key(dataset_config)
        if split_key not in self.preprocess_storage:
            preprocessor = dataset_config.get("preprocess")
            global_data = globals()[preprocessor](self.dataset[dataset_config["dataset_name"]],
                                                  self.dataset_split[split_key]) if preprocessor else None
            self.preprocess_storage[split_key] = global_data
        return self.preprocess_storage[split_key]

    def add_dataset(self, stage_config, dataset_config):
        data = self.get_ofa_data(dataset_config)
        split = self.get_data_split(dataset_config)
        stage_name = self.get_stage_name(stage_config, dataset_config)
        # Evaluation datasets are constructed only once.
        if stage_config["stage"] != "train" and stage_name in self.stage_names[stage_config["stage"]]:
            return self.stage_names[stage_config["stage"]].index(stage_name)
        global_data = self.get_global_data(dataset_config)
        prompt_feats = data.get_prompt_text_feat(dataset_config["task_level"])
        data = globals()[dataset_config["construct"]](dataset=data, split=split, split_name=stage_config["split_name"],
                                                      prompt_feats=prompt_feats, to_bin_cls_func=globals()[
                dataset_config["process_label_func"]] if dataset_config.get("process_label_func") else None,
                                                      task_level=dataset_config["task_level"], global_data=global_data,
                                                      **dataset_config["args"], )
        if stage_config["stage"] == "train":
            self.datasets[stage_config["stage"]].append(data)
        else:
            eval_data = make_data(stage_config["dataset"], data, stage_config["split_name"],
                                  dataset_config["eval_metric"], globals()[dataset_config["eval_func"]],
                                  dataset_config["num_classes"], batch_size=self.eval_batch_size,
                                  sample_size=self.sample_size, eval_mode=dataset_config["eval_mode"])
            self.datasets[stage_config["stage"]].append(eval_data)
        self.stage_names[stage_config["stage"]].append(stage_name)
        return self.stage_names[stage_config["stage"]].index(stage_name)

    def make_train_data(self, multiple, min_ratio, data_val_index=None):
        train_data = MultiDataset(self.datasets["train"], data_val_index=data_val_index, dataset_multiple=multiple,
                                  patience=3, window_size=5, min_ratio=min_ratio, )
        return train_data

    def make_full_dm_list(self, multiple, min_ratio, train_data=None):
        text_dataset = {
            "train": DataWithMeta(self.make_train_data(multiple, min_ratio) if not train_data else train_data,
                                  self.batch_size, sample_size=self.sample_size, ),
            "val": self.datasets["valid"],
            "test": self.datasets["test"], }
        return text_dataset

    def make_eval_dm_list(self):
        text_dataset = {
            "val": self.datasets["valid"],
            "test": self.datasets["test"], }
        return text_dataset

    def inject_tokenizer(self, tokenizer, max_length):
        for key, items in self.datasets.items():
            if key == "train":
                for dataset in items:
                    dataset.add_llm_tokenizer(tokenizer, max_length)
            else:
                for dataset in items:
                    dataset.data.add_llm_tokenizer(tokenizer, max_length)

