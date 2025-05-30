#    Copyright 2023 Haotian Liu
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.


import os
import warnings

from transformers import AutoTokenizer, AutoModelForCausalLM, AutoConfig, BitsAndBytesConfig
import torch
from model import NarGINALlamaForCausalLM
from utils.constants import DEFAULT_GRAPH_START_TOKEN, DEFAULT_GRAPH_END_TOKEN
import transformers

def check_lora_weight(adapter_path):
    state_dict = torch.load(adapter_path)

    # 创建一个新的字典，只修改键的名字
    new_state_dict = {key.replace("module.", "", 1) if key.startswith("module.") else key: value 
                    for key, value in state_dict.items()}

    # 保存新的权重文件
    torch.save(new_state_dict, adapter_path)

    #print("键名修改完成，新的权重文件已保存到")

def load_pretrained_model(model_path, model_base, model_name, load_8bit=False, load_4bit=False, device_map="auto", device="cuda", cache_dir="../../checkpoint"):
    kwargs = {"device_map": device_map}

    if load_8bit:
        kwargs['load_in_8bit'] = True
        print('8bit')
    elif load_4bit:
        kwargs['load_in_4bit'] = True
        kwargs['quantization_config'] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type='nf4'
        )
        print('4bit,nf4')
    else:
        kwargs['torch_dtype'] = torch.float16
#base_model.model.model.layers.31.mlp.down_proj.lora_B.weight
    if 'llaga' in model_name.lower():
        if 'lora' in model_name and model_base is None:
            warnings.warn('There is `lora` in model name but no `model_base` is provided. If you are loading a LoRA model, please provide the `model_base` argument. Detailed instruction: https://github.com/haotian-liu/LLaVA#launch-a-model-worker-lora-weights-unmerged.')
        if 'lora' in model_name and model_base is not None:
            print("load lora model...")
            check_lora_weight(model_path+'/adapter_model.bin')
            check_lora_weight(model_path+'/non_lora_trainables.bin')

            lora_cfg_pretrained = AutoConfig.from_pretrained(model_path)
            tokenizer = AutoTokenizer.from_pretrained(model_base, use_fast=False)
            print('Loading from base model...')
            model = NarGINALlamaForCausalLM.from_pretrained(model_base, low_cpu_mem_usage=True, config=lora_cfg_pretrained, cache_dir=cache_dir,  **kwargs)
            token_num, tokem_dim = model.lm_head.out_features, model.lm_head.in_features
            if model.lm_head.weight.shape[0] != token_num:
                model.lm_head.weight = torch.nn.Parameter(torch.empty(token_num, tokem_dim, device=model.device, dtype=model.dtype))
                model.model.embed_tokens.weight = torch.nn.Parameter(torch.empty(token_num, tokem_dim, device=model.device, dtype=model.dtype))

            print('Loading additional weights...')
            if os.path.exists(os.path.join(model_path, 'non_lora_trainables.bin')):
                non_lora_trainables = torch.load(os.path.join(model_path, 'non_lora_trainables.bin'), map_location='cpu')
            else:
                # this is probably from HF Hub
                from huggingface_hub import hf_hub_download
                def load_from_hf(repo_id, filename, subfolder=None):
                    cache_file = hf_hub_download(
                        repo_id=repo_id,
                        filename=filename,
                        subfolder=subfolder)
                    return torch.load(cache_file, map_location='cpu')
                non_lora_trainables = load_from_hf(model_path, 'non_lora_trainables.bin')
            non_lora_trainables = {(k[11:] if k.startswith('base_model.') else k): v for k, v in non_lora_trainables.items()}
            if any(k.startswith('model.model.') for k in non_lora_trainables):
                non_lora_trainables = {(k[6:] if k.startswith('model.') else k): v for k, v in non_lora_trainables.items()}
            model.load_state_dict(non_lora_trainables, strict=False)

            from peft import PeftModel
            print('Loading LoRA weights...')
            model = PeftModel.from_pretrained(model, model_path)
            print('Merging LoRA weights...')
            model = model.merge_and_unload()
            print('Model is loaded...')
        elif model_base is not None:
            # this may be mm projector only
            print('Loading from base model...')
            check_lora_weight(model_path+'/mm_projector.bin')
            # if 'mpt' in model_name.lower():
            #     if not os.path.isfile(os.path.join(model_path, 'configuration_mpt.py')):
            #         shutil.copyfile(os.path.join(model_base, 'configuration_mpt.py'), os.path.join(model_path, 'configuration_mpt.py'))
            #     tokenizer = AutoTokenizer.from_pretrained(model_base, use_fast=True)
            #     cfg_pretrained = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
            #     model = LlavaMPTForCausalLM.from_pretrained(model_base, low_cpu_mem_usage=True, config=cfg_pretrained, **kwargs)
            # else:
            #     tokenizer = AutoTokenizer.from_pretrained(model_base, use_fast=False)
            #     cfg_pretrained = AutoConfig.from_pretrained(model_path)
            #     model = LlavaLlamaForCausalLM.from_pretrained(model_base, low_cpu_mem_usage=True, config=cfg_pretrained, **kwargs)

            tokenizer = AutoTokenizer.from_pretrained(model_base, use_fast=False)
            cfg_pretrained = AutoConfig.from_pretrained(model_path)
            model = NarGINALlamaForCausalLM.from_pretrained(model_base, low_cpu_mem_usage=True, config=cfg_pretrained, cache_dir=cache_dir,
                                                        **kwargs)
            # model.get_model().initialize_graph_modules(cfg_pretrained)
            if os.path.exists(os.path.join(model_path, 'mm_projector.bin')):
                mm_projector_weights = torch.load(os.path.join(model_path, 'mm_projector.bin'), map_location='cpu')
                print("Load from mm_projector.bin")
            else:
                from huggingface_hub import hf_hub_download
                model_path_hf = hf_hub_download(repo_id=model_path,  filename='mm_projector.bin')
                mm_projector_weights = torch.load(model_path_hf, map_location='cpu')
                print("Load from huggingface")
            mm_projector_weights = {k: v.to(torch.float16) for k, v in mm_projector_weights.items()}
            model.load_state_dict(mm_projector_weights, strict=False)

            if os.path.exists(os.path.join(model_path, 'graph_encoder.bin')):
                graph_encoder_weights = torch.load(os.path.join(model_path, 'graph_encoder.bin'), map_location='cpu')
                print("Load from graph_encoder.bin")
                graph_encoder_weights = {k: v.to(torch.float16) for k, v in graph_encoder_weights.items()}
                model.load_state_dict(graph_encoder_weights, strict=False)


        else:
            # if 'mpt' in model_name.lower():
            #     tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)
            #     model = LlavaMPTForCausalLM.from_pretrained(model_path, low_cpu_mem_usage=True, **kwargs)
            # else:
            #     tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
            #     model = LlavaLlamaForCausalLM.from_pretrained(model_path, low_cpu_mem_usage=True, **kwargs)
            tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
            model = NarGINALlamaForCausalLM.from_pretrained(model_path, low_cpu_mem_usage=True, **kwargs)
    else:
        # Load language model
        if model_base is not None:
            # PEFT model
            check_lora_weight(model_path+'/adapter_model.bin')
            check_lora_weight(model_path+'/non_lora_trainables.bin')
            from peft import PeftModel
            tokenizer = AutoTokenizer.from_pretrained(model_base, use_fast=False)
            model = AutoModelForCausalLM.from_pretrained(model_base, torch_dtype=torch.float16, low_cpu_mem_usage=True, device_map="balanced", cache_dir=cache_dir)
            print(f"Loading LoRA weights from {model_path}")
            model = PeftModel.from_pretrained(model, model_path)
            print(f"Merging weights")
            model = model.merge_and_unload()
            print('Convert to FP16...')
            model.to(torch.float16)
        else:
            use_fast = False
            if 'mpt' in model_name.lower():
                tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True)
                model = AutoModelForCausalLM.from_pretrained(model_path, low_cpu_mem_usage=True, trust_remote_code=True, **kwargs)
            elif "t5" in model_name:
                tokenizer = transformers.T5Tokenizer.from_pretrained(model_path, use_fast=False)
                model = transformers.AutoModelForSeq2SeqLM.from_pretrained(model_path, low_cpu_mem_usage=True, cache_dir=cache_dir, **kwargs)
            else:
                tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=False)
                model = AutoModelForCausalLM.from_pretrained(model_path, low_cpu_mem_usage=True, cache_dir=cache_dir, **kwargs)


    if 'llaga' in model_name.lower():
        mm_use_graph_start_end = getattr(model.config, "mm_use_graph_start_end", False)
        if mm_use_graph_start_end:
            tokenizer.add_tokens([DEFAULT_GRAPH_START_TOKEN, DEFAULT_GRAPH_END_TOKEN], special_tokens=True)
        model.resize_token_embeddings(len(tokenizer))

    if hasattr(model.config, "max_sequence_length"):
        context_len = model.config.max_sequence_length
    else:
        context_len = 2048

    return tokenizer, model, context_len
