# modules/json_extractor.py
import json
import os
from typing import List, Dict, Optional

def extract_videos_from_json(json_path: str) -> Dict:
    """
    JSON file se sabhi videos extract karega
    Returns: {
        'batch_id': str,
        'batch_name': str,
        'videos': [
            {
                'subject_id': str,
                'subject_name': str,
                'topic_id': str,
                'topic_name': str,
                'title': str,
                'video_id': str,
                'child_id': str,
                'url': str,
                'duration': str,
                'createdAt': str
            }
        ]
    }
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        batch_id = data.get('batch', {}).get('id')
        batch_name = data.get('batch', {}).get('name', 'Unknown Batch')
        
        videos = []
        
        for subject in data.get('subjects', []):
            subject_id = subject.get('subjectId', '')
            subject_name = subject.get('subject', 'Unknown Subject')
            
            for topic in subject.get('topics', []):
                topic_id = topic.get('topicId', '')
                topic_name = topic.get('name', 'Unknown Topic')
                
                # Extract Lectures (Videos)
                for lecture in topic.get('lectures', []):
                    if lecture.get('videoId'):
                        videos.append({
                            'subject_id': subject_id,
                            'subject_name': subject_name,
                            'topic_id': topic_id,
                            'topic_name': topic_name,
                            'title': lecture.get('title', 'Untitled'),
                            'video_id': lecture.get('videoId'),
                            'child_id': lecture.get('_id', lecture.get('childId', '')),
                            'url': lecture.get('url', ''),
                            'duration': lecture.get('duration', ''),
                            'createdAt': lecture.get('createdAt', '')
                        })
                
                # Extract Notes (PDFs)
                for note in topic.get('notes', []):
                    if note.get('url'):
                        videos.append({
                            'subject_id': subject_id,
                            'subject_name': subject_name,
                            'topic_id': topic_id,
                            'topic_name': topic_name,
                            'title': note.get('name', 'Untitled Note'),
                            'video_id': '',
                            'child_id': '',
                            'url': note.get('url', ''),
                            'type': 'pdf',
                            'createdAt': ''
                        })
        
        return {
            'batch_id': batch_id,
            'batch_name': batch_name,
            'total_videos': len(videos),
            'videos': videos
        }
        
    except Exception as e:
        print(f"❌ Error extracting videos: {e}")
        return {'batch_id': '', 'batch_name': '', 'total_videos': 0, 'videos': []}

def get_video_by_id(json_path: str, video_id: str) -> Optional[Dict]:
    """
    JSON se specific video ID ke details fetch karega
    """
    data = extract_videos_from_json(json_path)
    for video in data.get('videos', []):
        if video.get('video_id') == video_id:
            return video
    return None

def get_videos_by_subject(json_path: str, subject_id: str) -> List[Dict]:
    """
    JSON se specific subject ke saare videos fetch karega
    """
    data = extract_videos_from_json(json_path)
    return [v for v in data.get('videos', []) if v.get('subject_id') == subject_id]
