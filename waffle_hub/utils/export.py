from pathlib import Path
from typing import Union

import tensorrt as trt
import torch

from waffle_hub import TaskType

PRECISION = {
    "fp32": torch.float32,
    "fp16": torch.float16,
    "int8": torch.int8,
}


def export_onnx(
    model: torch.nn.Module,
    task: Union[str, TaskType],
    output_path: Union[str, Path],
    image_size: Union[int, list[int]] = None,
    batch_size: int = 16,
    opset_version: int = 11,
    precision: str = "fp32",
    dynamic_batch: bool = False,
    device: str = "0",
) -> str:
    image_size = [image_size, image_size] if isinstance(image_size, int) else image_size

    precision = PRECISION[precision]

    device = torch.device(
        f"cuda:{device}" if torch.cuda.is_available() or device != "cpu" else "cpu"
    )
    model = model.to(device)

    input_name = ["inputs"]
    if task == TaskType.OBJECT_DETECTION:
        output_names = ["bbox", "conf", "class_id"]
    elif task == TaskType.CLASSIFICATION:
        output_names = ["predictions"]
    elif task == TaskType.INSTANCE_SEGMENTATION:
        output_names = ["bbox", "conf", "class_id", "masks"]
    elif task == TaskType.TEXT_RECOGNITION:
        output_names = ["class_ids", "confs"]
    else:
        raise NotImplementedError(f"{task} does not support export yet.")

    dummy_input = torch.randn(batch_size, 3, *image_size, dtype=precision)
    dummy_input = dummy_input.to(device)

    torch.onnx.export(
        model,
        dummy_input,
        str(output_path),
        input_names=input_name,
        output_names=output_names,
        opset_version=opset_version,
        dynamic_axes={name: {0: "batch_size"} for name in input_name + output_names}
        if dynamic_batch
        else None,
    )

    return str(output_path)


def export_engine(
    onnx_file: Union[str, Path],
    output_path: Union[str, Path],
    image_size: Union[int, list[int]] = None,
    batch_size: int = 16,
    precision: str = "fp32",
    dynamic_batch: bool = False,
    workspace: int = 4,
    device: str = "0",
):
    image_size = [image_size, image_size] if isinstance(image_size, int) else image_size

    precision = PRECISION[precision]

    device = torch.device(
        f"cuda:{device}" if torch.cuda.is_available() or device != "cpu" else "cpu"
    )
    model = model.to(device)

    logger = trt.Logger(trt.Logger.INFO)

    builder = trt.Builder(logger)
    config = builder.create_builder_config()
    config.max_workspace_size = workspace * 1 << 30

    flag = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(flag)
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(onnx_file):
        raise RuntimeError(f"failed to load ONNX file: {onnx_file}")

    inputs = [network.get_input(i) for i in range(network.num_inputs)]
    outputs = [network.get_output(i) for i in range(network.num_outputs)]
    for inp in inputs:
        print(f'input "{inp.name}" with shape{inp.shape} {inp.dtype}')
    for out in outputs:
        print(f'output "{out.name}" with shape{out.shape} {out.dtype}')

    if dynamic_batch:
        shape = [1, 3, *image_size]
        profile = builder.create_optimization_profile()
        for inp in inputs:
            profile.set_shape(inp.name, (1, *shape[1:]), (max(1, shape[0] // 2), *shape[1:]), shape)
        config.add_optimization_profile(profile)

    if builder.platform_has_fast_fp16 and True:
        config.set_flag(trt.BuilderFlag.FP16)

    # Write file
    with builder.build_engine(network, config) as engine, open(f, "wb") as t:
        # Metadata
        meta = json.dumps(self.metadata)
        t.write(len(meta).to_bytes(4, byteorder="little", signed=True))
        t.write(meta.encode())
        # Model
        t.write(engine.serialize())