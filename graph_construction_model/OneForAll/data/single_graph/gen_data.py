import importlib

import numpy as np

from OneForAll.data.ofa_data import OFAPygDataset

AVAILABLE_DATA = ["Cora", "Pubmed", "wikics", "arxiv","my_data_lev_l2lev_n","WN18RR_lev_l2lev_n","my_data_lev_l2lev_n_no_negative"]


class SingleGraphOFADataset(OFAPygDataset):
    def gen_data(self):
        if self.name not in AVAILABLE_DATA:
            raise NotImplementedError("Data " + self.name + " is not implemented")
        data_module = importlib.import_module("OneForAll.data.single_graph." + self.name + ".gen_data")
        return data_module.get_data(self)

    def add_raw_texts(self, data_list, texts):
        data_list[0].node_text_feat = np.array(texts[0])
        data_list[0].edge_text_feat = np.array(texts[1])
        data_list[0].noi_node_text_feat = np.array(texts[2])
        data_list[0].class_node_text_feat = np.array(texts[3])
        data_list[0].prompt_edge_text_feat = np.array(texts[4])
        return self.collate(data_list)

    def add_text_emb(self, data_list, text_emb):
        data_list[0].node_text_feat = text_emb[0]
        data_list[0].edge_text_feat = text_emb[1]
        data_list[0].noi_node_text_feat = text_emb[2]
        data_list[0].class_node_text_feat = text_emb[3]
        data_list[0].prompt_edge_text_feat = text_emb[4]
        return self.collate(data_list)

    def get_task_map(self):
        return self.side_data

    def get_edge_list(self, mode="e2e"):
        if mode == "e2e_node":
            return {"f2n": [1, [0]],
                    "n2f": [3, [0]],
                    "n2c": [2, [0]],
                    "c2n": [4, [0]]
                    }
        elif mode == "lr_node":
            return {"f2n": [1, [0]],
                    "n2f": [3, [0]],
                    }
        elif mode == "e2e_link":
            return {"f2n": [1, [0]], "n2f": [3, [0]], "n2c": [2, [0]], "c2n": [4, [0]]}