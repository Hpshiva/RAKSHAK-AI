"""
Monocular Person Height Estimation Engine for Surveillance Cameras
Combines:
1. Pinhole ground-plane perspective camera geometry
2. Anthropometric facial landmark and head-to-body ratio scaling
3. Temporal Exponential Moving Average (EMA) track stabilization
"""

import math
from typing import Dict, List, Optional, Tuple


def cm_to_feet_inches(height_cm: float) -> str:
    """Converts centimeter height into standard feet and inches string (e.g. 5'8\")."""
    total_inches = height_cm / 2.54
    feet = int(total_inches // 12)
    inches = int(round(total_inches % 12))
    if inches == 12:
        feet += 1
        inches = 0
    return f"{feet}'{inches}\""


def format_height(height_cm: float, show_range: bool = False, uncertainty_cm: float = 4.0) -> str:
    """Formats height exclusively in centimeters (e.g. 174 cm)."""
    cm_val = int(round(height_cm))
    if show_range:
        return f"{cm_val} cm ± {int(uncertainty_cm)} cm"
    return f"{cm_val} cm"


class HeightEstimator:
    def __init__(
        self,
        camera_height_m: float = 2.5,
        camera_tilt_deg: float = 28.0,
        vertical_fov_deg: float = 60.0,
    ):
        """
        Args:
            camera_height_m: Typical ceiling/wall CCTV mounting height in meters (default 2.5m / ~8.2ft).
            camera_tilt_deg: Downward pitch angle of the camera in degrees (default 28 degrees).
            vertical_fov_deg: Vertical field of view of the lens in degrees (default 60 degrees).
        """
        self.camera_height_m = camera_height_m
        self.camera_tilt_rad = math.radians(camera_tilt_deg)
        self.vertical_fov_rad = math.radians(vertical_fov_deg)
        
        # Track history for temporal EMA smoothing: {track_id: smoothed_height_cm}
        self.track_heights: Dict[int, float] = {}
        self.track_last_seen: Dict[int, int] = {}
        self.frame_counter: int = 0

    def estimate_height_geometric(
        self,
        bbox: Tuple[int, int, int, int],
        image_shape: Tuple[int, int, ...],
    ) -> float:
        """
        Estimates real-world height using ground-plane perspective projection.
        """
        img_h, img_w = image_shape[:2]
        x1, y1, x2, y2 = bbox
        box_h = max(1, y2 - y1)
        
        # Focal length in pixels
        fy = (img_h / 2.0) / math.tan(self.vertical_fov_rad / 2.0)
        cy = img_h / 2.0
        
        # Ground contact angle (feet)
        y_bottom = min(img_h - 1, max(0, y2))
        y_top = min(img_h - 1, max(0, y1))
        
        angle_bottom = math.atan((y_bottom - cy) / fy)
        total_angle_bottom = self.camera_tilt_rad + angle_bottom
        
        # Avoid division by zero or negative angles (above horizon)
        total_angle_bottom = max(math.radians(5.0), total_angle_bottom)
        
        # Ground distance Z from camera base
        dist_z = self.camera_height_m / math.tan(total_angle_bottom)
        
        # Angle to top of head
        angle_top = math.atan((y_top - cy) / fy)
        total_angle_top = self.camera_tilt_rad + angle_top
        
        # Physical height = Camera_Height - Z * tan(total_angle_top)
        raw_height_m = self.camera_height_m - (dist_z * math.tan(total_angle_top))
        raw_height_cm = raw_height_m * 100.0
        
        # Perspective scaling calibration:
        # If camera geometry is slightly uncalibrated, blend with standard human proportion prior
        norm_box_h = box_h / float(img_h)
        norm_y_pos = y_bottom / float(img_h)
        
        # Perspective reference: a full-height person at bottom frame is ~0.7-0.8 frame height, at horizon is smaller
        expected_ratio = max(0.15, min(0.85, 0.25 + 0.55 * (norm_y_pos ** 1.3)))
        perspective_scale = norm_box_h / expected_ratio
        calibrated_cm = 172.0 * perspective_scale
        
        # Blend geometric with calibrated prior
        if 130.0 <= raw_height_cm <= 215.0:
            final_cm = 0.65 * raw_height_cm + 0.35 * calibrated_cm
        else:
            final_cm = calibrated_cm
            
        # Biological boundary clamping (145 cm - 200 cm)
        return max(145.0, min(200.0, final_cm))

    def estimate_height_anthropometric(
        self,
        person_bbox: Tuple[int, int, int, int],
        face_bbox: Tuple[int, int, int, int],
    ) -> float:
        """
        Estimates height using head-to-body biological proportion (standard adult ~ 1:7.5).
        """
        px1, py1, px2, py2 = person_bbox
        fx1, fy1, fx2, fy2 = face_bbox
        
        body_h = max(1, py2 - py1)
        head_h = max(1, fy2 - fy1)
        
        head_body_ratio = body_h / float(head_h)
        # Standard human head is ~23 cm in vertical height
        estimated_cm = 23.0 * head_body_ratio
        
        return max(145.0, min(200.0, estimated_cm))

    def estimate_height(
        self,
        bbox: Tuple[int, int, int, int],
        image_shape: Tuple[int, int, ...],
        track_id: Optional[int] = None,
        face_bbox: Optional[Tuple[int, int, int, int]] = None,
    ) -> Tuple[float, str]:
        """
        Estimates the height of a person in cm and returns (height_cm, formatted_str).
        Applies EMA smoothing if a track_id is provided.
        """
        self.frame_counter += 1
        
        # 1. Geometric estimate
        geom_cm = self.estimate_height_geometric(bbox, image_shape)
        
        # 2. Anthropometric estimate (if face detected)
        if face_bbox is not None:
            anthro_cm = self.estimate_height_anthropometric(bbox, face_bbox)
            raw_cm = 0.55 * geom_cm + 0.45 * anthro_cm
        else:
            raw_cm = geom_cm
            
        # 3. Temporal EMA smoothing per track ID
        if track_id is not None:
            if track_id in self.track_heights:
                prev_cm = self.track_heights[track_id]
                smoothed_cm = 0.65 * prev_cm + 0.35 * raw_cm
            else:
                smoothed_cm = raw_cm
                
            self.track_heights[track_id] = smoothed_cm
            self.track_last_seen[track_id] = self.frame_counter
            
            # Prune stale tracks (>60 frames old)
            if self.frame_counter % 30 == 0:
                self.track_heights = {
                    tid: val for tid, val in self.track_heights.items()
                    if self.frame_counter - self.track_last_seen.get(tid, 0) <= 60
                }
                
            final_cm = smoothed_cm
        else:
            final_cm = raw_cm
            
        final_cm = round(final_cm, 1)
        formatted_str = format_height(final_cm)
        return final_cm, formatted_str

    def format_height_summary(self, heights: List[str]) -> str:
        """
        Combines a list of person height strings into a formatted summary string.
        e.g. ['175 cm', '168 cm'] -> '175 cm, 168 cm'
        """
        if not heights:
            return "Estimated ~172 cm"
        if len(heights) == 1:
            return heights[0]
        return ", ".join(f"Person {i+1}: {h}" for i, h in enumerate(heights))


# Global singleton instance
height_estimator = HeightEstimator()
