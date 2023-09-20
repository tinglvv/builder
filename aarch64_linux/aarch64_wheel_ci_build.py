#!/usr/bin/env python3
# encoding: UTF-8

import os
import subprocess
from pygit2 import Repository
from typing import List
import shutil


def list_dir(path: str) -> List[str]:
    ''''
    Helper for getting paths for Python
    '''
    return subprocess.check_output(["ls", "-1", path]).decode().split("\n")


def build_ArmComputeLibrary(git_clone_flags: str = "") -> None:
    '''
    Using ArmComputeLibrary for aarch64 PyTorch
    '''
    print('Building Arm Compute Library')
    os.system("cd / && mkdir /acl")
    os.system(f"git clone https://github.com/ARM-software/ComputeLibrary.git -b v23.05.1 {git_clone_flags}")
    os.system('sed -i -e \'s/"armv8.2-a"/"armv8-a"/g\' ComputeLibrary/SConscript; '
              'sed -i -e \'s/-march=armv8.2-a+fp16/-march=armv8-a/g\' ComputeLibrary/SConstruct; '
              'sed -i -e \'s/"-march=armv8.2-a"/"-march=armv8-a"/g\' ComputeLibrary/filedefs.json')
    os.system("cd ComputeLibrary; export acl_install_dir=/acl; "
              "scons Werror=1 -j8 debug=0 neon=1 opencl=0 os=linux openmp=1 cppthreads=0 arch=armv8.2-a multi_isa=1 build=native build_dir=$acl_install_dir/build; "
              "cp -r arm_compute $acl_install_dir; "
              "cp -r include $acl_install_dir; "
              "cp -r utils $acl_install_dir; "
              "cp -r support $acl_install_dir; "
              "cp -r src $acl_install_dir; cd /")


def complete_wheel(folder: str):
    '''
    Complete wheel build and put in artifact location
    '''
    wheel_name = list_dir(f"/{folder}/dist")[0]

    if "pytorch" in folder:
        print("Repairing Wheel with AuditWheel")
        os.system(f"cd /{folder}; auditwheel repair dist/{wheel_name}")
        repaired_wheel_name = list_dir(f"/{folder}/wheelhouse")[0]

        print(f"Moving {repaired_wheel_name} wheel to /{folder}/dist")
        os.system(f"mv /{folder}/wheelhouse/{repaired_wheel_name} /{folder}/dist/")
    else:
        repaired_wheel_name = wheel_name

    print(f"Copying {repaired_wheel_name} to artfacts")
    os.system(f"mv /{folder}/dist/{repaired_wheel_name} /artifacts/")

    return repaired_wheel_name


def update_wheel(wheel_path):
    folder = os.path.dirname(wheel_path)
    filename = os.path.basename(wheel_path)
    os.mkdir(f'{folder}/tmp')
    os.system(f'unzip {wheel_path} -d {folder}/tmp')
    libs_to_copy = [
        "/usr/local/cuda/lib64/libcudnn.so.8",
        "/usr/local/cuda/lib64/libcublas.so.11",
        "/usr/local/cuda/lib64/libcublasLt.so.11",
        "/usr/local/cuda/lib64/libcudart.so.11.0",
        "/usr/local/cuda/lib64/libnvToolsExt.so.1",
        "/usr/local/cuda/lib64/libnvrtc.so.11.2",
        "/usr/local/cuda/lib64/libnvrtc-builtins.so.11.8",
        "/opt/conda/lib/libgfortran.so.5",
        "/opt/conda/lib/libopenblas.so.0",
        "/opt/conda/lib/libgomp.so.1",
    ]
    # Copy libraries to unzipped_folder/a/lib
    for lib_path in libs_to_copy:
        lib_name = os.path.basename(lib_path)
        shutil.copy2(lib_path, f'{folder}/tmp/torch/lib/{lib_name}')
    os.system(f"cd {folder}/tmp/torch/lib/; patchelf --set-rpath '$ORIGIN' {folder}/tmp/torch/lib/libtorch_cuda.so")
    os.mkdir(f'{folder}/new_wheel')
    os.system(f'cd {folder}/tmp/; zip -r {folder}/new_wheel/{filename} *')
    os.system(f'rm -rf {folder}/tmp')


def parse_arguments():
    '''
    Parse inline arguments
    '''
    from argparse import ArgumentParser
    parser = ArgumentParser("AARCH64 wheels python CD")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--test-only", type=str)
    parser.add_argument("--enable-mkldnn", action="store_true")
    parser.add_argument("--enable-cuda", action="store_true")
    return parser.parse_args()


if __name__ == '__main__':
    '''
    Entry Point
    '''
    args = parse_arguments()
    enable_mkldnn = args.enable_mkldnn
    enable_cuda = args.enable_cuda
    repo = Repository('/pytorch')
    branch = repo.head.name
    if branch == 'HEAD':
        branch = 'master'

    git_clone_flags = " --depth 1 --shallow-submodules"

    print('Building PyTorch wheel')
    build_vars = "CMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=0x10000 "
    os.system("python setup.py clean")

    override_package_version = os.getenv("OVERRIDE_PACKAGE_VERSION")
    if override_package_version is not None:
        version = override_package_version
        build_vars += f"BUILD_TEST=0 PYTORCH_BUILD_VERSION={version} PYTORCH_BUILD_NUMBER=1 "
    else:
        if branch == 'nightly' or branch == 'master':
            build_date = subprocess.check_output(['git', 'log', '--pretty=format:%cs', '-1'], cwd='/pytorch').decode().replace('-', '')
            version = subprocess.check_output(['cat', 'version.txt'], cwd='/pytorch').decode().strip()[:-2]
            build_vars += f"BUILD_TEST=0 PYTORCH_BUILD_VERSION={version}.dev{build_date} PYTORCH_BUILD_NUMBER=1 "
        if branch.startswith("v1.") or branch.startswith("v2."):
            build_vars += f"BUILD_TEST=0 PYTORCH_BUILD_VERSION={branch[1:branch.find('-')]} PYTORCH_BUILD_NUMBER=1 "

    if enable_mkldnn:
        build_ArmComputeLibrary(git_clone_flags)
        print("build pytorch with mkldnn+acl backend")
        build_vars += "USE_MKLDNN=ON USE_MKLDNN_ACL=ON " \
                      "ACL_ROOT_DIR=/acl " \
                      "LD_LIBRARY_PATH=/pytorch/build/lib:/acl/build:$LD_LIBRARY_PATH " \
                      "ACL_INCLUDE_DIR=/acl/build " \
                      "ACL_LIBRARY=/acl/build "
    else:
        print("build pytorch without mkldnn backend")

    if enable_cuda:
        build_vars += 'TORCH_NVCC_FLAGS="-Xfatbin -compress-all --threads 2" USE_STATIC_CUDNN=0 ' \
            'NCCL_ROOT_DIR=/usr/local/cuda TH_BINARY_BUILD=1 USE_STATIC_NCCL=1 ATEN_STATIC_CUDA=1 ' \
            'USE_CUDA_STATIC_LINK=1 INSTALL_TEST=0 USE_CUPTI_SO=0  TORCH_CUDA_ARCH_LIST="5.0;6.0;7.0;7.5;8.0;8.6;3.7;9.0" ' \
            'EXTRA_CAFFE2_CMAKE_FLAGS="-DATEN_NO_TEST=ON" ' 

    os.system(f"cd /pytorch; {build_vars} python3 setup.py bdist_wheel")
    pytorch_wheel_name = complete_wheel("pytorch")
    print(f"Build Complete. Created {pytorch_wheel_name}..")
    print('Update the cuda dependency.')
    if enable_cuda:
        filename = os.listdir('/pytorch/dist/')
        wheel_path = f'/pytorch/dist/{filename[0]}'
        update_wheel(wheel_path)
