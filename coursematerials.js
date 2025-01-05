import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { useNavigate } from 'react-router-dom';
import 'bootstrap/dist/css/bootstrap.min.css';
import './courseMaterials.css';

const CourseMaterials = () => {
    const [sections, setSections] = useState([]);
    const [userPurchases, setUserPurchases] = useState({});
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();

    const user = JSON.parse(localStorage.getItem('user'));

    useEffect(() => {
        const fetchData = async () => {
            try {
                // Fetch course materials
                const materialsResponse = await axios.get('http://localhost:5000/api/course_materials');
                
                // Sort sections alphabetically by section name
                const sortedSections = materialsResponse.data.sections.sort((a, b) => 
                    a.name.localeCompare(b.name)
                );
   
                // Sort the items within each section by 'created_at' from older to newer
                const sortedSectionsWithItems = sortedSections.map(section => {
                    const sortedItems = section.items.sort((a, b) => 
                        new Date(a.created_at) - new Date(b.created_at) // Compare by created_at
                    );
                    return {
                        ...section,
                        items: sortedItems
                    };
                });
   
                setSections(sortedSectionsWithItems);
   
                // Fetch purchases as needed
                if (user) {
                    const purchases = {};
                    for (const section of sortedSectionsWithItems) {
                        try {
                            const response = await axios.get(
                                `http://localhost:5000/api/check-purchase/${section.name}`,
                                { params: { user_id: user.id } }
                            );
                            purchases[section.name] = response.data.has_access;
                        } catch (error) {
                            console.error(`Error checking purchase for ${section.name}:`, error);
                            purchases[section.name] = false;
                        }
                    }
                    setUserPurchases(purchases);
                }
            } catch (error) {
                console.error('Error fetching data:', error);
            } finally {
                setLoading(false);
            }
        };
   
        fetchData();
    }, [user?.id]); 
   
    const handlePurchase = async (sectionName) => {
        if (!user) {
            navigate('/login');
            return;
        }

        try {
            await axios.post('http://localhost:5000/api/purchase-section', {
                user_id: user.id,
                section_name: sectionName
            });
            
            // Update purchases state
            setUserPurchases(prev => ({
                ...prev,
                [sectionName]: true
            }));
            
            alert('Purchase successful!');
        } catch (error) {
            console.error('Error processing purchase:', error);
            alert('Error processing purchase. Please try again.');
        }
    };

    const canAccessContent = (sectionName, item) => {
        if (!item.authorized) return true; // Free preview content
        if (!user) return false; // Not logged in
        return userPurchases[sectionName]; // Check if purchased
    };

    if (loading) {
        return <div className="container mt-3">Loading...</div>;
    }

    return (
        <div className="container mt-3">
            <h1 className="text-center mb-4">Curriculum</h1>
            <div className="row">
                {sections.map(section => (
                    <div key={section.name} className="col-md-4 mb-4">
                        <div className="card h-100 shadow-sm">
                            <div className="card-header bg-primary text-white">
                                <h2 className="h5 text-center">{section.name}</h2>
                            </div>
                            <div className="card-body d-flex flex-column">
                                <ul className="list-group list-group-flush mb-3">
                                    {section.items.map(item => (
                                        <li key={item.name} className="list-group-item d-flex justify-content-between align-items-center">
                                            <span>{item.name}</span>
                                            <div className="course-action">
                                                {canAccessContent(section.name, item) ? (
                                                    <a 
                                                        href={`/playlist/${item.name}`} 
                                                        className="btn btn-primary btn-sm"
                                                    >
                                                        Start
                                                    </a>
                                                ) : item.authorized ? (
                                                    <button 
                                                        className="btn btn-secondary btn-sm" 
                                                        disabled
                                                    >
                                                        Locked
                                                    </button>
                                                ) : (
                                                    <a 
                                                        href={`/playlist/${item.name}`}
                                                        className="btn btn-success btn-sm"
                                                    >
                                                        Preview
                                                    </a>
                                                )}
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                                {!userPurchases[section.name] && (
                                    <button 
                                        className="btn btn-outline-primary mt-auto"
                                        onClick={() => handlePurchase(section.name)}
                                    >
                                        Purchase Now
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default CourseMaterials;