import json
import os
import time
from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
from transformers import TrainerCallback
from transformers.trainer_utils import PREFIX_CHECKPOINT_DIR, has_length

from .constants import LOG_FILE_NAME
from .logging import get_logger
from .misc import fix_valuehead_checkpoint, count_parameters
from ..hparams import FinetuningArguments

if TYPE_CHECKING:
    from transformers import TrainerControl, TrainerState, TrainingArguments

logger = get_logger(__name__)


class LisaTrainCallback(TrainerCallback):
    def __init__(self, finetuning_args: "FinetuningArguments", model: None):
        super().__init__()
        self.model = model
        self.layers_attribute = self.attention_layer_auto_detect(finetuning_args.lisa_attention_name)
        self.step_interval = finetuning_args.lisa_interval_steps
        self.lisa_activated_layers = finetuning_args.lisa_activated_layers
        self.total_layers = len(eval("self.model." + self.layers_attribute))
        self.lisa_verbose = finetuning_args.lisa_verbose

    def attention_layer_auto_detect(self, lisa_attention_name):
        _atten_val = lisa_attention_name
        if _atten_val is None:
            # Determine the way to access layers based on the model type
            if self.model.__class__.__name__ in ['LlamaForCausalLM', 'Qwen2ForCausalLM', 'MistralForCausalLM',
                                                 'GemmaForCausalLM']:
                _atten_val = 'model.layers'
            else:
                _atten_val = 'transformer.h'  # General access path
        return _atten_val

    def on_step_begin(self, args, state, control, **kwargs):
        if state.global_step % self.step_interval == 0:
            self.switch_active_layers()

    def freeze_all_layers(self):
        layers = eval("self.model." + self.layers_attribute)
        for layer in layers:
            for param in layer.parameters():
                param.requires_grad = False

    def switch_active_layers(self):
        # disable gradients for all layers
        self.freeze_all_layers()
        # seed, avoid fixed in other places
        np.random.seed(int(time.time()))
        layers = eval("self.model." + self.layers_attribute)
        active_layers_indices = np.random.choice(range(self.total_layers), self.lisa_activated_layers,
                                                 replace=False)
        for idx in active_layers_indices:
            for param in layers[idx].parameters():
                param.requires_grad = True
        if self.lisa_verbose:
            print('active_layers_indices', active_layers_indices)
            trainable_params, all_param = count_parameters(self.model)
            print("trainable params: {:d} || all params: {:d} || trainable%: {:.4f}".format(
                trainable_params, all_param, 100 * trainable_params / all_param
            ))


class FixValueHeadModelCallback(TrainerCallback):
    def on_save(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called after a checkpoint save.
        """
        if args.should_save:
            fix_valuehead_checkpoint(
                model=kwargs.pop("model"),
                output_dir=os.path.join(args.output_dir, "{}-{}".format(PREFIX_CHECKPOINT_DIR, state.global_step)),
                safe_serialization=args.save_safetensors,
            )


class LogCallback(TrainerCallback):
    def __init__(self, runner=None):
        self.runner = runner
        self.in_training = False
        self.start_time = time.time()
        self.cur_steps = 0
        self.max_steps = 0
        self.elapsed_time = ""
        self.remaining_time = ""

    def timing(self):
        cur_time = time.time()
        elapsed_time = cur_time - self.start_time
        avg_time_per_step = elapsed_time / self.cur_steps if self.cur_steps != 0 else 0
        remaining_time = (self.max_steps - self.cur_steps) * avg_time_per_step
        self.elapsed_time = str(timedelta(seconds=int(elapsed_time)))
        self.remaining_time = str(timedelta(seconds=int(remaining_time)))

    def on_train_begin(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called at the beginning of training.
        """
        if state.is_local_process_zero:
            self.in_training = True
            self.start_time = time.time()
            self.max_steps = state.max_steps

        if args.save_on_each_node:
            if not state.is_local_process_zero:
                return
        else:
            if not state.is_world_process_zero:
                return

        if os.path.exists(os.path.join(args.output_dir, LOG_FILE_NAME)) and args.overwrite_output_dir:
            logger.warning("Previous log file in this folder will be deleted.")
            os.remove(os.path.join(args.output_dir, LOG_FILE_NAME))

    def on_train_end(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called at the end of training.
        """
        if state.is_local_process_zero:
            self.in_training = False
            self.cur_steps = 0
            self.max_steps = 0

    def on_substep_end(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called at the end of an substep during gradient accumulation.
        """
        if state.is_local_process_zero and self.runner is not None and self.runner.aborted:
            control.should_epoch_stop = True
            control.should_training_stop = True

    def on_step_end(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called at the end of a training step.
        """
        if state.is_local_process_zero:
            self.cur_steps = state.global_step
            self.timing()
            if self.runner is not None and self.runner.aborted:
                control.should_epoch_stop = True
                control.should_training_stop = True

    def on_evaluate(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs):
        r"""
        Event called after an evaluation phase.
        """
        if state.is_local_process_zero and not self.in_training:
            self.cur_steps = 0
            self.max_steps = 0

    def on_predict(
            self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", *other, **kwargs
    ):
        r"""
        Event called after a successful prediction.
        """
        if state.is_local_process_zero and not self.in_training:
            self.cur_steps = 0
            self.max_steps = 0

    def on_log(self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs) -> None:
        r"""
        Event called after logging the last logs.
        """
        if args.save_on_each_node:
            if not state.is_local_process_zero:
                return
        else:
            if not state.is_world_process_zero:
                return

        logs = dict(
            current_steps=self.cur_steps,
            total_steps=self.max_steps,
            loss=state.log_history[-1].get("loss", None),
            eval_loss=state.log_history[-1].get("eval_loss", None),
            predict_loss=state.log_history[-1].get("predict_loss", None),
            reward=state.log_history[-1].get("reward", None),
            accuracy=state.log_history[-1].get("rewards/accuracies", None),
            learning_rate=state.log_history[-1].get("learning_rate", None),
            epoch=state.log_history[-1].get("epoch", None),
            percentage=round(self.cur_steps / self.max_steps * 100, 2) if self.max_steps != 0 else 100,
            elapsed_time=self.elapsed_time,
            remaining_time=self.remaining_time,
        )
        if self.runner is not None:
            logger.info(
                "{{'loss': {:.4f}, 'learning_rate': {:2.4e}, 'epoch': {:.2f}}}".format(
                    logs["loss"] or 0, logs["learning_rate"] or 0, logs["epoch"] or 0
                )
            )

        os.makedirs(args.output_dir, exist_ok=True)
        with open(os.path.join(args.output_dir, "trainer_log.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(logs) + "\n")

    def on_prediction_step(
            self, args: "TrainingArguments", state: "TrainerState", control: "TrainerControl", **kwargs
    ):
        r"""
        Event called after a prediction step.
        """
        eval_dataloader = kwargs.pop("eval_dataloader", None)
        if state.is_local_process_zero and has_length(eval_dataloader) and not self.in_training:
            if self.max_steps == 0:
                self.max_steps = len(eval_dataloader)
            self.cur_steps += 1
            self.timing()
