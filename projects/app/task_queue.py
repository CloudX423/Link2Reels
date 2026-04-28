"""
Link2Reels - 任务队列模块

支持多人同时使用的排队功能
"""

import os
import time
import uuid
import threading
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"      # 等待中
    PROCESSING = "processing"  # 处理中
    COMPLETED = "completed"    # 完成
    FAILED = "failed"          # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    session_id: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class TaskQueue:
    """任务队列管理器"""
    
    def __init__(self, max_concurrent: int = 1):
        """
        初始化队列
        
        Args:
            max_concurrent: 最大并发处理数，默认1（串行处理）
        """
        self._tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent
        self._processing_count = 0
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # 启动队列处理线程
        self._start_worker()
    
    def _start_worker(self):
        """启动后台工作线程"""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._worker_thread.start()
            logger.info("队列处理线程已启动")
    
    def add_task(self, session_id: str) -> str:
        """
        添加新任务到队列
        
        Args:
            session_id: 会话ID
            
        Returns:
            task_id: 新建的任务ID
        """
        task_id = uuid.uuid4().hex[:8]
        
        with self._lock:
            task = Task(task_id=task_id, session_id=session_id)
            self._tasks[task_id] = task
            logger.info(f"任务已添加: {task_id}, 会话: {session_id}")
        
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务信息"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_queue_info(self) -> Dict[str, Any]:
        """获取队列信息"""
        with self._lock:
            pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
            processing = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PROCESSING)
            completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
            failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
            
            return {
                "total": len(self._tasks),
                "pending": pending,
                "processing": processing,
                "completed": completed,
                "failed": failed,
                "max_concurrent": self._max_concurrent
            }
    
    def get_pending_position(self, task_id: str) -> int:
        """获取任务在队列中的位置"""
        with self._lock:
            pending_tasks = [
                t for t in self._tasks.values() 
                if t.status == TaskStatus.PENDING
            ]
            # 按创建时间排序
            pending_tasks.sort(key=lambda t: t.created_at)
            
            for i, t in enumerate(pending_tasks):
                if t.task_id == task_id:
                    return i + 1
            
            return -1  # 不在队列中
    
    def update_task_status(self, task_id: str, status: TaskStatus, 
                          progress: float = None, error: str = None,
                          result: Dict[str, Any] = None):
        """更新任务状态"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.status = status
                if progress is not None:
                    task.progress = progress
                if error is not None:
                    task.error = error
                if result is not None:
                    task.result = result
                
                if status == TaskStatus.PROCESSING and task.started_at is None:
                    task.started_at = datetime.now()
                elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    task.completed_at = datetime.now()
                    if status == TaskStatus.PROCESSING:
                        self._processing_count = max(0, self._processing_count - 1)
    
    def _process_queue(self):
        """后台队列处理循环"""
        while not self._stop_event.is_set():
            # 找待处理任务
            with self._lock:
                pending_tasks = [
                    t for t in self._tasks.values() 
                    if t.status == TaskStatus.PENDING
                ]
            
            if not pending_tasks:
                time.sleep(0.5)
                continue
            
            # 按创建时间排序
            pending_tasks.sort(key=lambda t: t.created_at)
            task = pending_tasks[0]
            
            logger.info(f"开始处理任务: {task.task_id}")
            self.update_task_status(task.task_id, TaskStatus.PROCESSING)
            
            # 注意: 实际的处理逻辑在 app.py 的 generate_video 中
            # 这里只是更新状态，任务处理是同步的
            # 队列的作用是让多个请求可以同时提交，后按顺序处理
            
            # 处理完成后标记（实际由 generate_video 路由更新）
            time.sleep(1)
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务"""
        with self._lock:
            now = datetime.now()
            to_remove = []
            
            for task_id, task in self._tasks.items():
                if task.completed_at:
                    age = (now - task.completed_at).total_seconds() / 3600
                    if age > max_age_hours:
                        to_remove.append(task_id)
            
            for task_id in to_remove:
                del self._tasks[task_id]
                logger.info(f"已清理旧任务: {task_id}")
            
            return len(to_remove)
    
    def stop(self):
        """停止队列"""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=2)


# 全局队列实例
task_queue = TaskQueue(max_concurrent=1)
