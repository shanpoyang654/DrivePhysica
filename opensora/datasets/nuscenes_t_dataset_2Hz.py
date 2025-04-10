
import logging

import mmcv
# from mmdet.datasets import DATASETS
from mmdet3d.datasets import NuScenesDataset
from mmdet3d.datasets.pipelines import LoadMultiViewImageFromFiles, Collect3D, LoadAnnotations3D

from PIL import Image, UnidentifiedImageError
from torchvision import transforms
import torch
import os
import numpy as np
import ipdb

# @DATASETS.register_module()
class NuScenesTDataset(NuScenesDataset):
    def __init__(
        self,
        ann_file,
        step=16,
        pipeline=None,
        dataset_root=None,
        object_classes=None,
        map_classes=None,
        load_interval=1,
        with_velocity=True,
        modality=None,
        box_type_3d="LiDAR", # The valid value are "LiDAR", "Camera", or "Depth".
        filter_empty_gt=True,
        test_mode=False,
        eval_version="detection_cvpr_2019",
        use_valid_flag=False,
        force_all_boxes=False,
        video_length=None,
        start_on_keyframe=True,
        start_on_firstframe=False,
        
        
        image_size: tuple = None,
        full_size: tuple = None,
        enable_scene_description: bool = False,
        additional_image_annotations: list = None,
        annotation: dict=None,
        fps=None,
        
    ) -> None:
        self.video_length = video_length
        self.start_on_keyframe = start_on_keyframe
        self.start_on_firstframe = start_on_firstframe
        self.step = step
        # original mmdet3d, 使用了bevfusion修改的nuscenes_dataset类
        super().__init__(
            ann_file, pipeline, dataset_root, object_classes, map_classes,
            load_interval, with_velocity, modality, box_type_3d,
            filter_empty_gt, test_mode, eval_version, use_valid_flag,
            force_all_boxes)

        # 尝试适配 mmdet3d v1.4.0, GG
        # super().__init__(
        #     dataset_root, ann_file, pipeline, object_classes, map_classes,
        #     load_interval, with_velocity, modality, box_type_3d,
        #     filter_empty_gt, test_mode, eval_version, use_valid_flag,
        #     force_all_boxes)
        
        self.image_size = image_size
        self.full_size = full_size
        self.enable_scene_description = enable_scene_description
        self.additional_image_annotations = additional_image_annotations
        self.annotation = annotation
        self.fps = fps
        
        self.transforms = transforms.Compose(
            [
                transforms.Resize(self.image_size),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5], inplace=True),
            ]
        )
        
        self.condition_transform = transforms.Compose([ 
            # transforms.Resize(self.image_size),
            transforms.Lambda(lambda img: self.resize_nearest(img, self.image_size)),
            transforms.ToTensor(),
            # transforms.Normalize(mean=[0.5, 0.5, 0.5], std=[0.5, 0.5, 0.5], inplace=True),
        ])
        
        if "12Hz" in ann_file and start_on_keyframe:
            logging.warn("12Hz should use all starting frame to train, please"
                         "double-check!")

    def build_clips(self, data_infos, scene_tokens):
        """Since the order in self.data_infos may change on loading, we
        calculate the index for clips after loading.

        Args:
            data_infos (list of dict): loaded data_infos
            scene_tokens (2-dim list of str): 2-dim list for tokens to each
            scene

        Returns:
            2-dim list of int: int is the index in self.data_infos
        """
        self.token_data_dict = {
            item['token']: idx for idx, item in enumerate(data_infos)}
        all_clips = []
        
        
        for scene in scene_tokens:
            # print("len(scene): ", len(scene)) # around 235
            # max_start = max(0, len(scene) - self.video_length + 1)
            for start in range(0, len(scene) - self.video_length + 1, self.step):
                if self.start_on_keyframe and ";" in scene[start]:
                    continue  # this is not a keyframe
                if self.start_on_keyframe and len(scene[start]) >= 33:
                    continue  # this is not a keyframe
                clip = [self.token_data_dict[token]
                        for token in scene[start: start + self.video_length]]
                all_clips.append(clip)
                if self.start_on_firstframe:
                    break
        logging.info(f"[{self.__class__.__name__}] Got {len(scene_tokens)} "
                     f"continuous scenes. Cut into {self.video_length}-clip, "
                     f"which has {len(all_clips)} in total.")
        return all_clips

    def load_annotations(self, ann_file):
        """Load annotations from ann_file.

        Args:
            ann_file (str): Path of the annotation file.

        Returns:
            list[dict]: List of annotations sorted by timestamps.
        """
        data = mmcv.load(ann_file) 
        '''
        dict_keys(['infos', 'metadata', 'scene_tokens'])
        infos: 165280
        metadata: version
        scene_tokens: 700 scenes
        '''

        data_infos = list(sorted(data["infos"], key=lambda e: e["timestamp"]))
        data_infos = data_infos[:: self.load_interval]
        
        '''
        dict_keys(['lidar_path', 'token', 'prev', 'next', 'can_bus', 'frame_idx', 'sweeps', 'cams', 'scene_token', 
        'lidar2ego_translation', 'lidar2ego_rotation', 'ego2global_translation', 'ego2global_rotation', 'timestamp', 
        'gt_boxes', 'gt_names', 'gt_velocity', 
        'num_lidar_pts', 'num_radar_pts', 'valid_flag'])
        
        data['infos'][0].keys()
        dict_keys(['lidar_path', 'token', 'sweeps', 'cams', 'lidar2ego_translation', 'lidar2ego_rotation', 'ego2global_translation',
        'ego2global_rotation', 'timestamp', 
        'location', 'description', 'timeofday', 'is_key_frame', 'visibility', 
        'gt_boxes', 'gt_names', 'gt_velocity', 'num_lidar_pts', 'num_radar_pts', 
        'valid_flag'])
        '''
        self.metadata = data["metadata"]
        self.version = self.metadata["version"]
        ipdb.set_trace()
        self.clip_infos = self.build_clips(data_infos, data['scene_tokens'])
        return data_infos

    def __len__(self):
        return len(self.clip_infos)

    def get_data_info(self, index):
        """We should sample from clip_infos
        """
        clip = self.clip_infos[index]
        frames = []
        for frame in clip:
            frame_info = super().get_data_info(frame) # 'ann_info'
            # info = self.data_infos[frame]
            frames.append(frame_info)
     
        return frames

    def resize_nearest(self, img, size):
        size = (size[1], size[0])
        return img.resize(size, Image.NEAREST)

        
    def prepare_train_data(self, index):
        """This is called by `__getitem__`
        """
        frames = self.get_data_info(index)
        if None in frames:
            return None
        examples = []
        for frame in frames:
            

            
            self.pre_pipeline(frame)
            example = self.pipeline(frame)

            # if self.filter_empty_gt and frame['is_key_frame'] and (
            #     example is None or ~(example["gt_labels_3d"]._data != -1).any()
            # ):
            #     return None
            
            if self.additional_image_annotations is not None:
                for data_dict in self.additional_image_annotations:
                    for key, root_path in data_dict.items():
                
                    
                        result_str = []
                        for img_path in example["metas"].data['filename']:  
                            relative_path = '/'.join(img_path.split('/')[-2:])        
                            new_filename = os.path.join(root_path, relative_path)
                            if os.path.exists(new_filename) and self.annotation[key]:
                                try:
                                    result_str.append(Image.open(new_filename))
                                except UnidentifiedImageError:
                                    print(f"UnidentifiedImageError: cannot identify image file '{new_filename}', using black image instead.")
                                    result_str.append(Image.new('RGB', (100, 100), 'black'))
                                except Exception as e:
                                    print(f"Unexpected error with file '{new_filename}': {str(e)}")
                                    result_str.append(Image.new('RGB', (100, 100), 'black'))
                            else:
                                # print(f"File '{new_filename}' does not exist, using black image instead.")
                                result_str.append(Image.new('RGB', (100, 100), 'black'))
                        
                        example[key] = result_str
                
            examples.append(example)    
                
        
        height = self.image_size[0]
        width = self.image_size[1]
        
 
        full_height = self.full_size[0]
        full_width = self.full_size[1]
        ar = width / height
        # ar = full_width / full_height # check ar
        results = {
            "video": torch.stack([torch.stack([self.transforms(i) for i in example['img']]) for example in examples]).permute(1, 2, 0, 3, 4), # [T, V, C, H, W] -> [V, C, T, H, W]
            "num_frames": self.video_length,
            "height": height,
            "width": width,
            "ar": ar,
            "full_height": full_height,
            "full_width": full_width,
            "hdmap": torch.stack([torch.stack([self.condition_transform(i) for i in example["hdmap"]]) for example in examples]).permute(1, 0, 2, 3, 4), # [T, V, C, H, W] -> [V, T, C, H, W]
            "bbox": torch.stack([torch.stack([self.condition_transform(i) for i in example["bbox"]]) for example in examples]).permute(1, 0, 2, 3, 4),
            "traj": torch.stack([torch.stack([self.condition_transform(i) for i in example["traj"]]) for example in examples]).permute(1, 0, 2, 3, 4),
            "fps": self.fps,
            # img_path
            "img_path": [example["metas"].data['filename'] for example in examples] # [T*[V]]
        }
        if self.enable_scene_description:
            results["text"] = frames[0]["description"]
        '''
        after transform:
        img:0-1
        hdmap:0-1
        '''
        # print(len([[img_path for img_path in example["metas"].data['filename']] for example in examples]))
        # print(len([[img_path for img_path in example["metas"].data['filename']] for example in examples][0]))
        return results

if __name__ == "__main__":
    # ann_file = "/mnt/iag/user/yangzhuoran/dataset/data/nuscenes_mmdet3d-12Hz/nuscenes_interp_12Hz_infos_train.pkl"
    # ann_file = "/mnt/iag/user/yangzhuoran/dataset/data/nuscenes_mmdet3d_2/nuscenes_infos_val.pkl"
    ann_file = "/mnt/iag/user/yangzhuoran/dataset/data/nuscenes_mmdet3d_2/nuscenes_infos_temporal_val.pkl"
    # cam2img
    pipeline = [
        LoadMultiViewImageFromFiles(camera_list=["CAM_FRONT_LEFT", "CAM_FRONT", "CAM_FRONT_RIGHT", "CAM_BACK_RIGHT", "CAM_BACK", "CAM_BACK_LEFT"]),
        LoadAnnotations3D(with_bbox_3d=True, with_label_3d=True, with_attr_label=False), # with_bbox=True, with_label=True,),
        Collect3D(
            keys=["img", 'description', 'gt_bboxes_3d', 'gt_labels_3d'],
            meta_keys=['camera_intrinsics', 'lidar2ego', 'lidar2camera', 'camera2lidar', 'lidar2image', 'img_aug_matrix'],
            meta_lis_keys=["filename", 'timeofday', 'location', 'token', 'description', 'cam2img']
        )
    ]
    modality = {
        "use_lidar": False,
        "use_camera": True,
        "use_radar": False,
        "use_map": False,
        "use_external": False
    }
    dataset = NuScenesTDataset( ann_file,
                                step=16, # 1
                                pipeline=pipeline,
                                modality=modality,
                                start_on_firstframe=False,
                                start_on_keyframe=False,
                                video_length = 16,
                                image_size = (288, 512),
                                full_size = (288, 512 * 6),
                                enable_scene_description = True,
                                additional_image_annotations = [{'bbox': '/mnt/iag/user/yangzhuoran/dataset/data/3dbox_test'},
                                                                {'hdmap': '/mnt/iag/user/yangzhuoran/dataset/data/hdmap_test'},
                                                                {'traj': '/mnt/iag/user/yangzhuoran/dataset/data/traj_test'},
                                                                ],
                                annotation={"hdmap":True,
                                            "bbox":True,
                                            "traj":False},
                                fps=12,
                            )
    for item in dataset:
        import pdb
        pdb.set_trace()
 
        
        
        
        